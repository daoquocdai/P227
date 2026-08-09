"""Phase G golden runner for realtime.py versus LegacyVisionEngine.

This module is intentionally not named ``test_*.py``: it is a controlled,
resource-backed measurement harness, not part of the fast unit suite.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import cv2
import numpy as np
import torch

from src.models.frame import FramePacket
from src.services.camera_runtime import CameraRuntime
from src.services.frame_hub import FrameHub
from src.services.stream_service import StreamService
from src.services.vision_manager import VisionManager
from src.services.vision_sample_buffer import VisionSampleBuffer
from src.vision.adapters.legacy import LegacyVisionEngine
from src.vision.model.SDAGCN import Model
from src.vision.session import VisionSession

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VISION_ROOT = PROJECT_ROOT / "src" / "vision"
NORMAL_VIDEO = VISION_ROOT / "demo" / "videodemo" / "demo.mp4"
FALL_CANDIDATE_VIDEO = PROJECT_ROOT / "frontend" / "public" / "videos" / "kich_ban3.mp4"


@dataclass
class GoldenTrace:
    name: str
    sampled_frame_ids: list[int] = field(default_factory=list)
    sampled_timestamps: list[float] = field(default_factory=list)
    window_frame_ids: list[list[int]] = field(default_factory=list)
    window_timestamps: list[list[float]] = field(default_factory=list)
    arrays: dict[str, list[np.ndarray]] = field(default_factory=lambda: defaultdict(list))
    timings_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    state_observations: list[dict[str, Any]] = field(default_factory=list)
    result_observations: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    processing_ms: list[float] = field(default_factory=list)
    published_frame_ids: list[int] = field(default_factory=list)
    published_timestamps: list[float] = field(default_factory=list)
    consumed_frame_ids: list[int] = field(default_factory=list)
    consumed_timestamps: list[float] = field(default_factory=list)
    system_observation: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        classes = [int(array.argmax(axis=-1).reshape(-1)[0]) for array in self.arrays["probabilities"]]
        return {
            "name": self.name,
            "sampled_frame_ids": self.sampled_frame_ids,
            "window_frame_ids": self.window_frame_ids,
            "window_durations": [timestamps[-1] - timestamps[0] for timestamps in self.window_timestamps],
            "model_input_shapes": [list(value.shape) for value in self.arrays["model_input"]],
            "logits": [value.tolist() for value in self.arrays["logits"]],
            "probabilities": [value.tolist() for value in self.arrays["probabilities"]],
            "classes": classes,
            "events": self.events,
            "state_observations": self.state_observations,
            "timings_ms": {
                name: percentile_summary(values)
                for name, values in self.timings_ms.items()
                if values
            },
            "processing_ms": percentile_summary(self.processing_ms),
            "published_frame_ids": self.published_frame_ids,
            "published_timestamps": self.published_timestamps,
            "consumed_frame_ids": self.consumed_frame_ids,
            "consumed_timestamps": self.consumed_timestamps,
            "sampling": sampling_summary(self),
            "system_observation": self.system_observation,
        }


class SourceCursor:
    def __init__(self) -> None:
        self.frame_id = -1
        self.timestamp = 0.0


class LoopingVideoCapture:
    def __init__(self, video_path: Path, max_frames: int, cursor: SourceCursor) -> None:
        self._capture = cv2.VideoCapture(str(video_path))
        if not self._capture.isOpened():
            raise RuntimeError(f"Cannot open golden video: {video_path}")
        self._max_frames = max_frames
        self._read_count = 0
        self._cursor = cursor
        self._fps = self._capture.get(cv2.CAP_PROP_FPS) or 30.0

    def isOpened(self) -> bool:
        return self._capture.isOpened()

    def read(self):
        if self._read_count >= self._max_frames:
            return False, None
        ok, frame = self._capture.read()
        if not ok:
            self._capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self._capture.read()
        if not ok:
            return False, None
        self._cursor.frame_id = self._read_count
        self._cursor.timestamp = self._read_count / self._fps
        self._read_count += 1
        return True, frame

    def release(self) -> None:
        self._capture.release()


class DisabledFaceAnalysis:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def prepare(self, *args, **kwargs) -> None:
        pass

    def get(self, _image) -> list:
        return []


class TimedPose:
    def __init__(self, inner: Any, trace: GoldenTrace) -> None:
        self._inner = inner
        self._trace = trace

    def process(self, image):
        started = time.perf_counter()
        try:
            return self._inner.process(image)
        finally:
            self._trace.timings_ms["pose"].append((time.perf_counter() - started) * 1000)

    def close(self) -> None:
        self._inner.close()


class TimedYolo:
    def __init__(self, inner: Any, trace: GoldenTrace, cursor: SourceCursor) -> None:
        self._inner = inner
        self._trace = trace
        self._cursor = cursor

    def to(self, device):
        self._inner.to(device)
        return self

    def track(self, *args, **kwargs):
        self._trace.sampled_frame_ids.append(self._cursor.frame_id)
        self._trace.sampled_timestamps.append(self._cursor.timestamp)
        started = time.perf_counter()
        try:
            results = self._inner.track(*args, **kwargs)
        finally:
            self._trace.timings_ms["yolo"].append((time.perf_counter() - started) * 1000)
        boxes = results[0].boxes if results else None
        xyxy = np.empty((0, 4), dtype=np.float32) if boxes is None else boxes.xyxy.detach().cpu().numpy().copy()
        self._trace.arrays["yolo_xyxy"].append(xyxy)
        return results


class RecordingModel:
    def __init__(self, inner: Any, trace: GoldenTrace) -> None:
        self._inner = inner
        self._trace = trace

    def to(self, device):
        self._inner.to(device)
        return self

    def load_state_dict(self, *args, **kwargs):
        return self._inner.load_state_dict(*args, **kwargs)

    def eval(self):
        self._inner.eval()
        return self

    def __call__(self, tensor):
        self._trace.arrays["model_input"].append(tensor.detach().cpu().numpy().copy())
        started = time.perf_counter()
        try:
            output = self._inner(tensor)
        finally:
            self._trace.timings_ms["sda_gcn"].append((time.perf_counter() - started) * 1000)
        logits = output.detach().cpu().numpy().copy()
        probabilities = torch.softmax(output, dim=1).detach().cpu().numpy().copy()
        self._trace.arrays["logits"].append(logits)
        self._trace.arrays["probabilities"].append(probabilities)
        return output


class StageRecorder:
    def __init__(self, trace: GoldenTrace, cursor: SourceCursor, *, record_heavy_arrays: bool = True) -> None:
        self.trace = trace
        self.cursor = cursor
        self.record_heavy_arrays = record_heavy_arrays

    def yolo_factory(self, yolo_class):
        def create(*args, **kwargs):
            return TimedYolo(yolo_class(*args, **kwargs), self.trace, self.cursor)

        return create

    def pose_factory(self, pose_class):
        def create(*args, **kwargs):
            return TimedPose(pose_class(*args, **kwargs), self.trace)

        return create

    def model_factory(self):
        trace = self.trace

        class Factory:
            def __new__(cls, **kwargs):
                return RecordingModel(Model(**kwargs), trace)

        return Factory

    def wrap_stages(self, namespace: Any) -> None:
        original_clean = namespace.clean_out_of_bounds_data
        original_extract = namespace.extract_from_crop
        original_dynamic = namespace.normalize_skeleton_dynamic
        original_normalize = namespace.normalize_pose
        original_interpolate = namespace.interpolate_missing
        original_kalman = namespace.apply_kalman_filter

        def extract(crop, pose, x_min, y_min, crop_w, crop_h, orig_w, orig_h):
            self.trace.arrays["pose_crop_bbox"].append(
                np.asarray([x_min, y_min, crop_w, crop_h, orig_w, orig_h], dtype=np.float32)
            )
            if self.record_heavy_arrays:
                self.trace.arrays["pose_input_rgb"].append(crop.copy())
            output = original_extract(crop, pose, x_min, y_min, crop_w, crop_h, orig_w, orig_h)
            if self.record_heavy_arrays:
                self.trace.arrays["raw_pose_frame"].append(output.copy())
            return output

        def clean(value):
            self.trace.arrays["raw_ntu25"].append(value.copy())
            self.trace.window_frame_ids.append(self.trace.sampled_frame_ids[-64:].copy())
            self.trace.window_timestamps.append(self.trace.sampled_timestamps[-64:].copy())
            return self._timed_array("clean", original_clean, value)

        def dynamic(value):
            return self._timed_array("dynamic", original_dynamic, value)

        def normalize(value):
            self.trace.arrays["second_root_subtraction"].append(value.copy())
            return self._timed_array("normalize_pose", original_normalize, value)

        def interpolate(value):
            return self._timed_array("interpolate", original_interpolate, value)

        def kalman(value):
            return self._timed_array("kalman", original_kalman, value)

        namespace.extract_from_crop = extract
        namespace.clean_out_of_bounds_data = clean
        namespace.normalize_skeleton_dynamic = dynamic
        namespace.normalize_pose = normalize
        namespace.interpolate_missing = interpolate
        namespace.apply_kalman_filter = kalman

    def _timed_array(self, name: str, function, value):
        started = time.perf_counter()
        output = function(value)
        self.trace.timings_ms[name].append((time.perf_counter() - started) * 1000)
        self.trace.arrays[name].append(output.copy())
        return output


def run_reference(
    video_path: Path = NORMAL_VIDEO,
    max_frames: int = 127,
    *,
    render_overlays: bool = True,
    record_heavy_arrays: bool = True,
) -> GoldenTrace:
    from src.vision import realtime

    trace = GoldenTrace("legacy-overlay" if render_overlays else "legacy-clean-v1")
    cursor = SourceCursor()
    recorder = StageRecorder(trace, cursor, record_heavy_arrays=record_heavy_arrays)
    capture = LoopingVideoCapture(video_path.resolve(), max_frames, cursor)
    original_yolo = realtime.YOLO
    original_pose = realtime.mp.solutions.pose.Pose
    stage_names = (
        "extract_from_crop",
        "clean_out_of_bounds_data",
        "normalize_skeleton_dynamic",
        "normalize_pose",
        "interpolate_missing",
        "apply_kalman_filter",
    )
    original_stages = {name: getattr(realtime, name) for name in stage_names}
    recorder.wrap_stages(realtime)

    previous_cwd = Path.cwd()
    previous_trace = sys.gettrace()

    def state_tracer(frame, event, arg):
        if frame.f_code is realtime.main.__code__ and event == "line" and frame.f_lineno in {219, 232, 241}:
            local = frame.f_locals
            trace.state_observations.append(
                {
                    "frame_id": cursor.frame_id,
                    "captured_at": cursor.timestamp,
                    "observed_at": time.time(),
                    "line": frame.f_lineno,
                    "pending_fall": bool(local.get("pending_fall", False)),
                    "current_action": local.get("current_action"),
                    "pred_idx": local.get("pred_idx"),
                }
            )
        return state_tracer

    try:
        os.chdir(VISION_ROOT)
        with ExitStack() as stack:
            stack.enter_context(patch.object(realtime.cv2, "VideoCapture", lambda *args, **kwargs: capture))
            stack.enter_context(patch.object(realtime.cv2, "imshow", lambda *args, **kwargs: None))
            stack.enter_context(patch.object(realtime.cv2, "waitKey", lambda *args, **kwargs: -1))
            stack.enter_context(patch.object(realtime.cv2, "destroyAllWindows", lambda: None))
            if not render_overlays:
                stack.enter_context(patch.object(realtime.cv2, "rectangle", lambda *args, **kwargs: None))
                stack.enter_context(patch.object(realtime.cv2, "putText", lambda *args, **kwargs: None))
            stack.enter_context(patch.object(realtime, "YOLO", recorder.yolo_factory(original_yolo)))
            stack.enter_context(patch.object(realtime, "FaceAnalysis", DisabledFaceAnalysis))
            stack.enter_context(patch.object(realtime.mp.solutions.pose, "Pose", recorder.pose_factory(original_pose)))
            stack.enter_context(patch.object(realtime, "import_class", lambda _name: recorder.model_factory()))
            sys.settrace(state_tracer)
            realtime.main()
    finally:
        sys.settrace(previous_trace)
        for name, function in original_stages.items():
            setattr(realtime, name, function)
        os.chdir(previous_cwd)
        capture.release()
    return trace


def run_direct(
    video_path: Path = NORMAL_VIDEO,
    max_frames: int = 127,
    *,
    record_heavy_arrays: bool = True,
) -> GoldenTrace:
    trace = GoldenTrace("DIRECT-LegacyVisionEngine")
    cursor = SourceCursor()
    recorder = StageRecorder(trace, cursor, record_heavy_arrays=record_heavy_arrays)
    engine = LegacyVisionEngine(identity_enabled=False)
    engine.start()
    engine._ensure_initialized()
    assert engine._dependencies is not None
    dependencies = engine._dependencies
    original_yolo = dependencies.YOLO
    original_pose = dependencies.mp.solutions.pose.Pose
    dependencies.YOLO = recorder.yolo_factory(original_yolo)
    dependencies.mp = SimpleNamespace(
        solutions=SimpleNamespace(
            pose=SimpleNamespace(Pose=recorder.pose_factory(original_pose)),
        )
    )
    recorder.wrap_stages(dependencies)
    engine._action_model = RecordingModel(engine._action_model, trace)
    session = VisionSession("golden-direct")

    capture = LoopingVideoCapture(video_path.resolve(), max_frames, cursor)
    previous_state = None
    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            result = engine.process(
                FramePacket(
                    camera_id=session.camera_id,
                    frame_id=cursor.frame_id,
                    captured_at=cursor.timestamp,
                    frame=frame,
                ),
                session,
            )
            trace.processing_ms.append(result.processing_ms)
            state = result.metadata["fall_state"]
            if state != previous_state or result.metadata["raw_class"] is not None or result.events:
                trace.result_observations.append(
                    {
                        "frame_id": result.frame_id,
                        "captured_at": result.captured_at,
                        "processed_at": result.processed_at,
                        "fall_state": state,
                        "pending_fall": result.metadata["pending_fall"],
                        "raw_class": result.metadata["raw_class"],
                        "probabilities": result.metadata["probabilities"],
                        "logits": result.metadata["logits"],
                        "model_window_index": result.metadata["model_window_index"],
                        "window_frame_ids": result.metadata["window_frame_ids"],
                        "window_captured_at": result.metadata["window_captured_at"],
                        "incident_id": result.metadata["incident_id"],
                        "event_count": len(result.events),
                    }
                )
            previous_state = state
            for event in result.events:
                trace.events.append(
                    {
                        "frame_id": result.frame_id,
                        "type": event.type,
                        "confidence": event.confidence,
                        "metadata": event.metadata,
                    }
                )
    finally:
        capture.release()
        engine.stop()
    return trace


class RecordingFrameHub(FrameHub):
    """Test-only FrameHub observer; latest-frame semantics remain unchanged."""

    def __init__(self, trace: GoldenTrace) -> None:
        super().__init__()
        self._trace = trace
        self._record_lock = threading.Lock()

    def publish(self, packet: FramePacket):
        with self._record_lock:
            self._trace.published_frame_ids.append(packet.frame_id)
            self._trace.published_timestamps.append(packet.captured_at)
        return super().publish(packet)


class RecordingLegacyVisionEngine(LegacyVisionEngine):
    """Test-only observer around the production adapter's process boundary."""

    def __init__(self, trace: GoldenTrace, cursor: SourceCursor) -> None:
        super().__init__(identity_enabled=False)
        self._golden_trace = trace
        self._golden_cursor = cursor

    def process(self, packet: FramePacket, session: VisionSession):
        self._golden_cursor.frame_id = packet.frame_id
        self._golden_cursor.timestamp = packet.captured_at
        self._golden_trace.consumed_frame_ids.append(packet.frame_id)
        self._golden_trace.consumed_timestamps.append(packet.captured_at)
        result = super().process(packet, session)
        self._golden_trace.processing_ms.append(result.processing_ms)
        metadata = result.metadata
        observation = {
            "frame_id": result.frame_id,
            "captured_at": result.captured_at,
            "processed_at": result.processed_at,
            "fall_state": metadata["fall_state"],
            "pending_fall": metadata["pending_fall"],
            "raw_class": metadata["raw_class"],
            "probabilities": metadata["probabilities"],
            "logits": metadata["logits"],
            "model_window_index": metadata["model_window_index"],
            "window_frame_ids": metadata["window_frame_ids"],
            "window_captured_at": metadata["window_captured_at"],
            "source_frame_gap": metadata["source_frame_gap"],
            "event_count": len(result.events),
        }
        if (
            not self._golden_trace.result_observations
            or observation["fall_state"] != self._golden_trace.result_observations[-1]["fall_state"]
            or observation["raw_class"] is not None
            or result.events
        ):
            self._golden_trace.result_observations.append(observation)
        for event in result.events:
            self._golden_trace.events.append(
                {
                    "frame_id": result.frame_id,
                    "captured_at": result.captured_at,
                    "processed_at": result.processed_at,
                    "type": event.type,
                    "confidence": event.confidence,
                    "metadata": event.metadata,
                }
            )
        return result


def instrument_engine(engine: LegacyVisionEngine, trace: GoldenTrace, cursor: SourceCursor) -> None:
    engine.start()
    engine._ensure_initialized()
    assert engine._dependencies is not None
    dependencies = engine._dependencies
    recorder = StageRecorder(trace, cursor, record_heavy_arrays=False)
    dependencies.YOLO = recorder.yolo_factory(dependencies.YOLO)
    original_pose = dependencies.mp.solutions.pose.Pose
    dependencies.mp = SimpleNamespace(
        solutions=SimpleNamespace(
            pose=SimpleNamespace(Pose=recorder.pose_factory(original_pose)),
        )
    )
    recorder.wrap_stages(dependencies)
    engine._action_model = RecordingModel(engine._action_model, trace)


def run_local_hub(
    video_path: Path = NORMAL_VIDEO,
    *,
    target_windows: int | None = 1,
    loop_video: bool = True,
    timeout: float = 180.0,
) -> GoldenTrace:
    """Measure the real CameraRuntime -> FrameHub -> VisionWorker path."""

    trace = GoldenTrace("REAL-LOCAL-HUB")
    cursor = SourceCursor()
    hub = RecordingFrameHub(trace)
    sample_buffer = VisionSampleBuffer()
    engine = RecordingLegacyVisionEngine(trace, cursor)
    instrument_engine(engine, trace, cursor)
    camera = CameraRuntime(hub, vision_sample_buffer=sample_buffer)
    stream = StreamService(hub)
    manager = VisionManager(hub, engine, sample_buffer=sample_buffer)
    camera_id = "golden-local"
    mjpeg_ok = False
    deadline = time.monotonic() + timeout

    try:
        manager.start()
        manager.enable(camera_id)
        camera.start(camera_id, str(video_path.resolve()), loop_video=loop_video)
        while time.monotonic() < deadline and not hub.has_camera(camera_id):
            time.sleep(0.01)
        if hub.has_camera(camera_id):
            mjpeg_ok = next(stream.mjpeg(camera_id)).startswith(b"--frame\r\nContent-Type: image/jpeg")

        while time.monotonic() < deadline:
            status = camera.get_status(camera_id) or {}
            vision_status = manager.get_status(camera_id)
            if target_windows is not None and len(trace.window_frame_ids) >= target_windows:
                last_window_frame_id = trace.window_frame_ids[target_windows - 1][-1]
                if vision_status["last_processed_frame_id"] >= last_window_frame_id:
                    break
            if not loop_video and status.get("status") == "ended":
                latest = hub.get_latest(camera_id)
                if latest is None or vision_status["last_processed_frame_id"] >= latest.frame_id:
                    break
            time.sleep(0.02)
        else:
            raise TimeoutError(
                f"Local Hub golden measurement timed out after {timeout}s "
                f"with {len(trace.window_frame_ids)} model windows"
            )

        trace.system_observation = {
            "camera_status": camera.get_status(camera_id),
            "vision_status": manager.get_status(camera_id),
            "mjpeg_ok": mjpeg_ok,
            "worker_running": manager.worker.is_running,
        }
    finally:
        camera.stop(camera_id, remove_frame=False)
        manager.stop()
        trace.system_observation["worker_running_after_stop"] = manager.worker.is_running
        trace.system_observation["camera_status_after_stop"] = camera.get_status(camera_id)
        trace.system_observation["vision_status_after_stop"] = manager.get_status(camera_id)
    return trace


def compare_traces(reference: GoldenTrace, direct: GoldenTrace) -> dict[str, Any]:
    stages = [
        "yolo_xyxy",
        "pose_crop_bbox",
        "pose_input_rgb",
        "raw_pose_frame",
        "raw_ntu25",
        "clean",
        "dynamic",
        "second_root_subtraction",
        "normalize_pose",
        "interpolate",
        "kalman",
        "model_input",
        "logits",
        "probabilities",
    ]
    comparisons = {}
    first_divergence = None
    for stage in stages:
        old_values = reference.arrays[stage]
        new_values = direct.arrays[stage]
        entry: dict[str, Any] = {
            "old_count": len(old_values),
            "direct_count": len(new_values),
        }
        if len(old_values) != len(new_values):
            entry["comparable"] = False
            first_divergence = first_divergence or stage
        elif not old_values:
            entry["comparable"] = True
        else:
            differences = [np.abs(old - new) for old, new in zip(old_values, new_values)]
            nonempty_differences = [difference for difference in differences if difference.size]
            entry.update(
                {
                    "comparable": True,
                    "shapes_equal": all(old.shape == new.shape for old, new in zip(old_values, new_values)),
                    "max_abs": max(float(diff.max(initial=0.0)) for diff in differences),
                    "mean_abs": (
                        float(np.mean([difference.mean() for difference in nonempty_differences]))
                        if nonempty_differences
                        else 0.0
                    ),
                    "exact_equal": all(np.array_equal(old, new) for old, new in zip(old_values, new_values)),
                }
            )
            if entry["max_abs"] != 0.0:
                first_divergence = first_divergence or stage
        comparisons[stage] = entry
    return {
        "sampling_ids_equal": reference.sampled_frame_ids == direct.sampled_frame_ids,
        "window_ids_equal": reference.window_frame_ids == direct.window_frame_ids,
        "first_divergence": first_divergence,
        "stages": comparisons,
    }


def percentile_summary(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "p50": None, "p95": None, "mean": None}
    array = np.asarray(values, dtype=np.float64)
    return {
        "count": len(values),
        "p50": float(np.percentile(array, 50)),
        "p95": float(np.percentile(array, 95)),
        "mean": float(array.mean()),
    }


def sampling_summary(trace: GoldenTrace) -> dict[str, Any]:
    sample_gaps = np.diff(trace.sampled_frame_ids)
    windows = []
    for frame_ids, timestamps in zip(trace.window_frame_ids, trace.window_timestamps):
        gaps = np.diff(frame_ids)
        windows.append(
            {
                "first_frame_id": frame_ids[0],
                "last_frame_id": frame_ids[-1],
                "average_source_frame_gap": float(gaps.mean()) if len(gaps) else 0.0,
                "max_source_frame_gap": int(gaps.max()) if len(gaps) else 0,
                "source_frame_span": frame_ids[-1] - frame_ids[0],
                "first_captured_at": timestamps[0],
                "last_captured_at": timestamps[-1],
                "time_span": timestamps[-1] - timestamps[0],
            }
        )
    consumed_gaps = np.diff(trace.consumed_frame_ids)
    return {
        "sample_count": len(trace.sampled_frame_ids),
        "average_sample_gap": float(sample_gaps.mean()) if len(sample_gaps) else None,
        "max_sample_gap": int(sample_gaps.max()) if len(sample_gaps) else None,
        "consumed_count": len(trace.consumed_frame_ids),
        "average_consumed_gap": float(consumed_gaps.mean()) if len(consumed_gaps) else None,
        "max_consumed_gap": int(consumed_gaps.max()) if len(consumed_gaps) else None,
        "windows": windows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, default=NORMAL_VIDEO)
    parser.add_argument("--frames", type=int, default=127)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--legacy-overlay",
        action="store_true",
        help="Use historical UI-mutated Pose input instead of the approved legacy-clean-v1 oracle",
    )
    args = parser.parse_args()

    reference = run_reference(args.video, args.frames, render_overlays=args.legacy_overlay)
    direct = run_direct(args.video, args.frames)
    report = {
        "video": str(args.video.resolve()),
        "frames": args.frames,
        "oracle": "legacy-overlay" if args.legacy_overlay else "legacy-clean-v1",
        "reference": reference.summary(),
        "direct": direct.summary(),
        "comparison": compare_traces(reference, direct),
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
