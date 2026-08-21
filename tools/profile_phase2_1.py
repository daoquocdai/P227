"""Controlled Phase 2.1 profiler. Not part of the application runtime."""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import psutil

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sda_vision import VisionCallbacks, VisionSession, VisionSessionConfig

from src.integrations.sda_vision import SdaSessionRegistry, SdaVisionFacade
from src.services.frame_hub import FrameHub
from src.services.stream_service import StreamService

WINDOWS = (("startup", 0.0, 5.0), ("transition", 5.0, 10.0), ("steady", 10.0, 30.0))


def summary(values):
    values = [float(value) for value in values if value is not None]
    if not values:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "max": None}
    return {
        "count": len(values),
        "mean": statistics.fmean(values),
        "p50": float(np.percentile(values, 50)),
        "p95": float(np.percentile(values, 95)),
        "max": max(values),
    }


class Collector:
    def __init__(self):
        self.started = time.monotonic()
        self.started_wall = time.time()
        self.source_times = []
        self.result_times = []
        self.states = []
        self.cpu_samples = []
        self._sample_stop = threading.Event()
        psutil.cpu_percent(interval=None)
        self._sample_thread = threading.Thread(target=self._sample_resources, daemon=True)
        self._sample_thread.start()

    def _sample_resources(self):
        while not self._sample_stop.wait(1.0):
            self.cpu_samples.append((time.monotonic(), psutil.cpu_percent(interval=None)))

    def stop_sampling(self):
        self._sample_stop.set()
        self._sample_thread.join(2)

    def source(self, _frame):
        self.source_times.append(time.monotonic())

    def result(self, _frame, result):
        now = time.monotonic()
        self.result_times.append(now)
        state = result.detections[0].identity_state if result.detections else None
        if not self.states or self.states[-1][1] != state:
            self.states.append((now, state))


def window_profile(collector, profile, start, end):
    absolute_start = collector.started + start
    absolute_end = collector.started + end
    def in_window(timestamp):
        return absolute_start <= timestamp < absolute_end
    source_count = sum(in_window(value) for value in collector.source_times)
    result_count = sum(in_window(value) for value in collector.result_times)
    pose = [value for timestamp, value in profile["pose"] if in_window(timestamp)]
    sda = [value for timestamp, value, *_rest in profile["sda_gcn"] if in_window(timestamp)]
    identity = [value for timestamp, value, *_rest in profile["identity"] if in_window(timestamp)]
    cycles = [value for timestamp, value in profile["cycle"] if in_window(timestamp)]
    source_callback = [value for timestamp, value in profile["source_callback"] if in_window(timestamp)]
    result_callback = [value for timestamp, value in profile["result_callback"] if in_window(timestamp)]
    duration = end - start
    return {
        "source_fps": source_count / duration,
        "vision_fps": result_count / duration,
        "pose_ms": summary(pose),
        "sda_gcn_ms": summary(sda),
        "identity_ms": summary(identity),
        "identity_inferences_per_s": len(identity) / duration,
        "total_cycle_ms": summary(cycles),
        "source_callback_ms": summary(source_callback),
        "result_callback_ms": summary(result_callback),
    }


def finish(case, collector, session, extra=None, duration=30.0):
    collector.stop_sampling()
    profile = session.performance_profile()
    windows = {
        name: window_profile(collector, profile, start, end)
        for name, start, end in WINDOWS
    }
    correlations = []
    identities = profile["identity"]
    for observed, latency, state, started_wall, finished_wall in identities:
        overlapping = [
            {"finished_s": sda_finished_wall - collector.started_wall, "latency_ms": sda_latency}
            for _observed, sda_latency, _started, _count, sda_started_wall, sda_finished_wall
            in profile["sda_gcn"]
            if started_wall is not None and sda_started_wall is not None
            and sda_started_wall <= finished_wall and started_wall <= sda_finished_wall
        ]
        correlations.append({
            "identity_observed_s": observed - collector.started,
            "identity_started_s": None if started_wall is None else started_wall - collector.started_wall,
            "identity_finished_s": None if finished_wall is None else finished_wall - collector.started_wall,
            "identity_ms": latency,
            "state": state,
            "overlapping_sda": overlapping,
        })
    identity_intervals = [
        (started_wall, finished_wall)
        for _observed, _latency, _state, started_wall, finished_wall in identities
        if started_wall is not None and finished_wall is not None
    ]
    sda_overlap, sda_non_overlap = [], []
    for _observed, latency, _started, _count, started_wall, finished_wall in profile["sda_gcn"]:
        target = sda_overlap if any(
            identity_start <= finished_wall and started_wall <= identity_finish
            for identity_start, identity_finish in identity_intervals
        ) else sda_non_overlap
        target.append(latency)
    identity_overlap_count = sum(bool(item["overlapping_sda"]) for item in correlations)
    minute_windows = {}
    for minute_start in range(0, int(duration), 60):
        minute_end = min(duration, minute_start + 60)
        if minute_end - minute_start < 30:
            continue
        window = window_profile(collector, profile, minute_start, minute_end)
        cpu = [value for timestamp, value in collector.cpu_samples
               if collector.started + minute_start <= timestamp < collector.started + minute_end]
        window["system_cpu_percent"] = summary(cpu)
        minute_windows[f"minute_{minute_start // 60 + 1}"] = window
    return {
        "case": case,
        "windows": windows,
        "identity_states": [(timestamp - collector.started, state) for timestamp, state in collector.states],
        "identity_sda_correlations": correlations,
        "sda_invocations": len(profile["sda_gcn"]),
        "sda_invocation_ids_unique": len({item[3] for item in profile["sda_gcn"]}),
        "scheduler_deadline_misses": profile["scheduler_deadline_misses"],
        "capture_frames_dropped": profile["capture_frames_dropped"],
        "identity_queue": profile.get("identity_queue", {}),
        "minute_windows": minute_windows,
        "overlap_metrics": {
            "sda_overlap_ms": summary(sda_overlap),
            "sda_non_overlap_ms": summary(sda_non_overlap),
            "identity_calls_overlapping_sda": identity_overlap_count,
            "identity_calls_not_overlapping_sda": len(correlations) - identity_overlap_count,
        },
        **(extra or {}),
    }


def run_standalone(source, identity, duration, *, loop_video=False):
    collector = Collector()
    session = VisionSession(VisionSessionConfig(
        source=source, camera_id="profile", device="auto", identity_enabled=identity,
        vision_fps=15.0, preview="none", log_level="error", loop_video=loop_video),
        VisionCallbacks(on_source_frame=collector.source, on_result_frame=collector.result))
    thread = threading.Thread(target=session.run, name="profile-standalone")
    thread.start()
    time.sleep(duration)
    session.request_stop()
    thread.join(10)
    if thread.is_alive():
        raise RuntimeError("standalone session did not stop")
    return finish(f"standalone_identity_{'on' if identity else 'off'}", collector, session, duration=duration)


class Dispatcher:
    def __init__(self):
        self.results = []

    def dispatch(self, result):
        self.results.append((time.monotonic(), result))
        return True


def run_integrated(source, identity, with_client, duration, *, process_priority="normal",
                   cpu_affinity=None):
    collector = Collector()
    dispatcher = Dispatcher()
    settings = SimpleNamespace(
        vision_identity_enabled=identity, vision_device="auto", vision_fps=15.0,
        vision_identity_process_priority=process_priority,
        vision_identity_cpu_affinity=cpu_affinity, log_level="error")
    hub = FrameHub()
    registry = SdaSessionRegistry(hub, settings=settings, event_dispatcher=dispatcher)
    registry.start()
    registry.set_identity_enabled("profile", identity)
    original_source = registry._on_source
    original_result = registry._on_result

    def source_callback(camera_id, frame):
        collector.source(frame)
        original_source(camera_id, frame)

    def result_callback(camera_id, frame, result):
        collector.result(frame, result)
        original_result(camera_id, frame, result)

    registry._on_source = source_callback
    registry._on_result = result_callback
    stream = StreamService(hub, vision=SdaVisionFacade(registry))
    client_stop = threading.Event()

    async def consume():
        async def disconnected():
            return client_stop.is_set()
        async for _chunk in stream.mjpeg_async("profile", disconnected):
            if client_stop.is_set():
                break

    client_thread = None
    if with_client:
        client_thread = threading.Thread(target=lambda: asyncio.run(consume()), name="profile-mjpeg")
        client_thread.start()
    registry.start_session("profile", source, loop_video=False, location="Profile")
    session = registry._records["profile"].session
    time.sleep(duration)
    client_stop.set()
    registry.stop_session("profile")
    if client_thread:
        client_thread.join(5)
        if client_thread.is_alive():
            raise RuntimeError("MJPEG client did not stop")
    event_profile = registry._events.profile()
    jpeg_samples = stream.jpeg_profile_samples()
    registry.stop_all()
    jpeg_windows = {}
    for name, start, end in WINDOWS:
        values = [value for timestamp, value in jpeg_samples
                  if collector.started + start <= timestamp < collector.started + end]
        jpeg_windows[name] = {
            "calls_per_s": len(values) / (end - start),
            "latency_ms": summary(values),
        }
    event_latencies = [value for _timestamp, value in event_profile["samples"]]
    snapshot_latencies = [value for _timestamp, value in event_profile["snapshot_samples"]]
    return finish(
        f"integrated_identity_{'on' if identity else 'off'}_client_{with_client}",
        collector, session,
        {"jpeg": jpeg_windows,
         "events": {"submitted": event_profile["submitted"],
                    "processed_latency_ms": summary(event_latencies),
                    "max_queue_depth": event_profile["max_queue_depth"],
                    "final_queue_depth": event_profile["current_queue_depth"]},
         "snapshots": {"calls": len(snapshot_latencies),
                       "latency_ms": summary(snapshot_latencies)},
         "candidate": {"identity_process_priority": process_priority,
                       "identity_cpu_affinity": cpu_affinity,
                       "cpu_logical": psutil.cpu_count(logical=True),
                       "cpu_physical": psutil.cpu_count(logical=False),
                       "allowed_affinity": (psutil.Process().cpu_affinity()
                                            if hasattr(psutil.Process(), "cpu_affinity") else None)},
         "dispatched_events": len(dispatcher.results)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--duration", type=float, default=31.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--only-on", action="store_true")
    parser.add_argument("--integrated-mjpeg-only", action="store_true")
    parser.add_argument("--integrated-mjpeg-on-only", action="store_true")
    parser.add_argument("--standalone-on-only", action="store_true")
    parser.add_argument("--loop-video", action="store_true")
    parser.add_argument("--identity-priority", choices=("normal", "below_normal"), default="normal")
    parser.add_argument("--identity-affinity", help="Comma-separated allowed logical CPU IDs")
    args = parser.parse_args()
    affinity = (tuple(int(value) for value in args.identity_affinity.split(","))
                if args.identity_affinity else None)
    tuning = {"process_priority": args.identity_priority, "cpu_affinity": affinity}
    if args.standalone_on_only:
        cases = [run_standalone(args.source, True, args.duration, loop_video=args.loop_video)]
    elif args.integrated_mjpeg_on_only:
        cases = [run_integrated(args.source, True, True, args.duration, **tuning)]
    elif args.integrated_mjpeg_only:
        cases = [
            run_integrated(args.source, False, True, args.duration),
            run_integrated(args.source, True, True, args.duration, **tuning),
        ]
    elif args.only_on:
        cases = [
            run_standalone(args.source, True, args.duration),
            run_integrated(args.source, True, False, args.duration),
            run_integrated(args.source, True, True, args.duration),
        ]
    else:
        cases = [
            run_standalone(args.source, False, args.duration),
            run_standalone(args.source, True, args.duration),
            run_integrated(args.source, False, False, args.duration),
            run_integrated(args.source, True, False, args.duration),
            run_integrated(args.source, False, True, args.duration),
            run_integrated(args.source, True, True, args.duration),
        ]
    args.output.write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print(json.dumps({item["case"]: {
        "steady": item["windows"]["steady"],
        "misses": item["scheduler_deadline_misses"],
        "events": item.get("events"),
    } for item in cases}, indent=2))


if __name__ == "__main__":
    main()
