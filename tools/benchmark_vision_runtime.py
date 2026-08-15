"""Benchmark canonical Vision scheduling with deterministic video sources.

This tool is deliberately outside the production runtime. It compares the
current shared sequential scheduler with ordered per-camera workers while using
the same pipeline, sampler, models, and source-time contract.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import cv2  # noqa: E402

from src.models.frame import FramePacket  # noqa: E402
from src.services.frame_hub import FrameHub  # noqa: E402
from src.services.vision_sample_buffer import VisionSampleBuffer  # noqa: E402
from src.vision.pipeline import CanonicalVisionPipeline  # noqa: E402
from src.vision.session import VisionSession  # noqa: E402
from src.vision.worker import VisionWorker  # noqa: E402


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * fraction))
    return float(ordered[index])


def process_memory_mb() -> float | None:
    try:
        import psutil

        return psutil.Process().memory_info().rss / (1024 * 1024)
    except ImportError:
        return None


class VideoSource:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.capture = cv2.VideoCapture(str(path))
        if not self.capture.isOpened():
            raise RuntimeError(f"Cannot open video: {path}")
        self.fps = float(self.capture.get(cv2.CAP_PROP_FPS) or 30.0)
        self.frame_id = 0

    def read_looping(self):
        ok, frame = self.capture.read()
        if not ok:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
        if not ok:
            raise RuntimeError(f"Cannot read video: {self.path}")
        frame_id = self.frame_id
        self.frame_id += 1
        return frame_id, frame

    def close(self) -> None:
        self.capture.release()


class BenchmarkRun:
    def __init__(
        self,
        sources: dict[str, Path],
        *,
        target_hz: float,
        duration: float,
        scheduler: str,
        identity_enabled: bool,
    ) -> None:
        self.sources = sources
        self.target_hz = target_hz
        self.duration = duration
        self.scheduler = scheduler
        self.buffer = VisionSampleBuffer(
            target_sample_rate=target_hz,
            inference_skip_factor=2,
            capacity=8,
        )
        self.engine = CanonicalVisionPipeline(
            device="auto",
            identity_enabled=identity_enabled,
        )
        self.sessions = {camera_id: VisionSession(camera_id=camera_id) for camera_id in sources}
        self.results: dict[str, list[Any]] = {camera_id: [] for camera_id in sources}
        self.events: dict[str, list[dict[str, Any]]] = {camera_id: [] for camera_id in sources}
        self.errors: list[str] = []
        self.stop_event = threading.Event()
        self.threads: list[threading.Thread] = []
        self.worker: VisionWorker | None = None

    def run(self) -> dict[str, Any]:
        if self.scheduler == "production":
            self.worker = VisionWorker(
                FrameHub(),
                self.engine,
                on_result=self._record_result,
                on_error=self._record_error,
                sample_buffer=self.buffer,
            )
            self.worker.start()
            for camera_id in self.sources:
                self.sessions[camera_id] = self.worker.enable(camera_id)
        else:
            self.engine.start()
            for camera_id, session in self.sessions.items():
                self.buffer.enable(camera_id)
                self.engine.prepare_camera(camera_id, session)

        videos = {camera_id: VideoSource(path) for camera_id, path in self.sources.items()}
        memory_before = process_memory_mb()
        wall_started = time.perf_counter()
        cpu_started = time.process_time()
        if self.scheduler != "production":
            self._start_consumers()
        try:
            deadline = wall_started + self.duration
            source_period = min(1.0 / source.fps for source in videos.values())
            next_frame_at = wall_started
            while time.perf_counter() < deadline and not self.errors:
                for camera_id, source in videos.items():
                    frame_id, frame = source.read_looping()
                    self.buffer.offer(
                        FramePacket(
                            camera_id=camera_id,
                            frame_id=frame_id,
                            captured_at=time.time(),
                            frame=frame,
                            source_timestamp=frame_id / source.fps,
                            source_time_kind="media_timeline",
                            source_epoch=0,
                            discontinuity=frame_id == 0,
                        )
                    )
                next_frame_at += source_period
                remaining = next_frame_at - time.perf_counter()
                if remaining > 0:
                    time.sleep(remaining)

            drain_deadline = time.monotonic() + 5.0
            while time.monotonic() < drain_deadline:
                if all(self.buffer.get_status(camera_id)["buffer_depth"] == 0 for camera_id in self.sources):
                    break
                time.sleep(0.02)
        finally:
            self.stop_event.set()
            diagnostics = self.engine.device_diagnostics()
            if self.worker is not None:
                worker_threads = self.worker.thread_count
                self.worker.stop()
            else:
                worker_threads = len([thread for thread in self.threads if thread.is_alive()])
                for thread in self.threads:
                    thread.join(timeout=5)
            for source in videos.values():
                source.close()
            wall_elapsed = time.perf_counter() - wall_started
            cpu_elapsed = time.process_time() - cpu_started
            memory_after = process_memory_mb()
            if self.worker is None:
                self.engine.stop()

        return {
            "scheduler": self.scheduler,
            "target_hz": self.target_hz,
            "duration_seconds": wall_elapsed,
            "camera_count": len(self.sources),
            "cpu_core_equivalent_percent": cpu_elapsed / wall_elapsed * 100,
            "memory_rss_before_mb": memory_before,
            "memory_rss_after_mb": memory_after,
            "device": diagnostics,
            "worker_threads": worker_threads,
            "errors": self.errors,
            "cameras": {
                camera_id: self._camera_summary(camera_id)
                for camera_id in self.sources
            },
        }

    def _start_consumers(self) -> None:
        if self.scheduler == "sequential":
            thread = threading.Thread(target=self._sequential_loop, name="benchmark-sequential", daemon=True)
            self.threads.append(thread)
            thread.start()
            return
        for camera_id in self.sources:
            thread = threading.Thread(
                target=self._camera_loop,
                args=(camera_id,),
                name=f"benchmark-{camera_id}",
                daemon=True,
            )
            self.threads.append(thread)
            thread.start()

    def _sequential_loop(self) -> None:
        self._consumer_loop(lambda: list(self.sources))

    def _camera_loop(self, camera_id: str) -> None:
        self._consumer_loop(lambda: [camera_id])

    def _consumer_loop(self, cameras: Callable[[], list[str]]) -> None:
        version = self.buffer.version
        while not self.stop_event.is_set():
            processed = False
            for camera_id in cameras():
                packet = self.buffer.get_nowait(camera_id)
                if packet is None:
                    continue
                processed = True
                self._process(camera_id, packet)
            if not processed:
                version = self.buffer.wait_for_update(version, timeout=0.1)

    def _process(self, camera_id: str, packet: FramePacket) -> None:
        session = self.sessions[camera_id]
        if packet.frame_id <= session.last_processed_frame_id:
            return
        session.note_frame(packet.frame_id)
        try:
            result = self.engine.process(packet, session)
        except Exception as exc:
            self.errors.append(f"{camera_id} frame={packet.frame_id}: {exc}")
            session.mark_processed(packet.frame_id)
            return
        session.mark_processed(packet.frame_id)
        self.buffer.note_result(packet, result.metadata)
        self._record_result(result)

    def _record_error(self, camera_id: str, frame_id: int, exc: Exception) -> None:
        self.errors.append(f"{camera_id} frame={frame_id}: {exc}")

    def _record_result(self, result) -> None:
        camera_id = result.camera_id
        self.results[camera_id].append(result)
        for event in result.events:
            self.events[camera_id].append(
                {
                    "frame_id": result.frame_id,
                    "type": event.type,
                    "confidence": event.confidence,
                    "event_id": event.metadata.get("event_id"),
                }
            )

    def _camera_summary(self, camera_id: str) -> dict[str, Any]:
        results = self.results[camera_id]
        sampled = [result for result in results if result.metadata.get("sampled")]
        processing = [result.processing_ms for result in sampled]
        model_results = [result for result in results if result.metadata.get("raw_class") is not None]
        status = self.buffer.get_status(camera_id)
        session = self.sessions[camera_id]
        last = results[-1].metadata if results else {}
        return {
            "processed_frames": session.processed_frames,
            "frame_sequence_drops": session.dropped_frames,
            "sampled_results": len(sampled),
            "model_windows": len(model_results),
            "predicted_classes": [result.metadata["raw_class"] for result in model_results],
            "last_window_source_span": status["window_source_time_span"],
            "effective_hz": status["effective_sample_rate"],
            "service_hz": status["service_rate"],
            "input_drops": status["input_drop_count"],
            "temporal_drops": status["temporal_drop_count"],
            "overloads": status["overload_count"],
            "temporal_fidelity": status["temporal_fidelity"],
            "processing_ms": {
                "p50": percentile(processing, 0.50),
                "p95": percentile(processing, 0.95),
                "mean": statistics.fmean(processing) if processing else 0.0,
            },
            "stage_metrics": last.get("performance", {}),
            "events": self.events[camera_id],
        }


def camera_sources(values: list[str]) -> dict[str, Path]:
    parsed = {}
    for value in values:
        camera_id, separator, raw_path = value.partition("=")
        if not separator or not camera_id or not raw_path:
            raise ValueError("--camera must use CAMERA_ID=VIDEO_PATH")
        path = Path(raw_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if not path.is_file():
            raise FileNotFoundError(path)
        parsed[camera_id] = path.resolve()
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--camera", action="append", required=True, help="CAMERA_ID=VIDEO_PATH")
    parser.add_argument("--target-hz", type=float, required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument(
        "--scheduler",
        choices=("sequential", "per-camera", "production"),
        default="sequential",
    )
    parser.add_argument("--identity", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))
    report = BenchmarkRun(
        camera_sources(args.camera),
        target_hz=args.target_hz,
        duration=args.duration,
        scheduler=args.scheduler,
        identity_enabled=args.identity,
    ).run()
    payload = json.dumps(report, indent=2)
    print(payload)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
