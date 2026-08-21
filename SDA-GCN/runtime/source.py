"""Unified latest-frame sources with explicit semantic and runtime clocks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import threading
import time

import cv2

from .pipeline import LatestFrameStore


class SourceKind(str, Enum):
    CAMERA = "camera"
    VIDEO_FILE = "video_file"
    STREAM = "stream"


@dataclass(frozen=True)
class FramePacket:
    sequence: int
    frame: object
    source_time_s: float
    captured_monotonic_s: float
    source_frame_index: int | None = None
    wall_time_utc: datetime | None = None


@dataclass(frozen=True)
class SourceSpec:
    kind: SourceKind
    value: object


@dataclass
class SourceMetadata:
    kind: SourceKind
    name: str
    width: int | None = None
    height: int | None = None
    source_fps: float | None = None
    frame_count: int | None = None
    duration_s: float | None = None
    timestamp_strategy: str = "unknown"


def parse_source(value: str) -> SourceSpec:
    path = Path(value).expanduser()
    if path.exists():
        if not path.is_file():
            raise ValueError(f"Video source is not a file: {path}")
        return SourceSpec(SourceKind.VIDEO_FILE, path.resolve())
    if value.isdecimal():
        return SourceSpec(SourceKind.CAMERA, int(value))
    if value.lower().startswith(("rtsp://", "http://", "https://")):
        return SourceSpec(SourceKind.STREAM, value)
    raise ValueError(f"Video file does not exist: {path}")


class FrameSource:
    def __init__(self):
        self.store = LatestFrameStore()
        self.metadata = None
        self.capture_fps = 0.0
        self.error = None
        self.ended = False
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = None

    def start(self, timeout=5.0):
        self._thread = threading.Thread(target=self._run, name="vision-source", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        if self.error:
            raise RuntimeError(self.error)
        if self.store.latest() is None:
            raise RuntimeError("Source did not produce a frame within the startup timeout.")

    def stop(self, timeout=2.0):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def _run(self):
        raise NotImplementedError


class CameraSource(FrameSource):
    def __init__(self, index: int):
        super().__init__()
        self.index = index

    def _run(self):
        capture = cv2.VideoCapture(self.index, cv2.CAP_DSHOW)
        if not capture.isOpened():
            self.error = f"Camera {self.index} cannot open."
            self._ready.set()
            return
        reported_fps = float(capture.get(cv2.CAP_PROP_FPS))
        source_fps = reported_fps if 0 < reported_fps < 1000 else None
        self.metadata = SourceMetadata(
            SourceKind.CAMERA, f"Camera {self.index}",
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            source_fps, timestamp_strategy="monotonic",
        )
        sequence = 0
        measured_at, measured_frames = time.perf_counter(), 0
        try:
            while not self._stop.is_set():
                ok, frame = capture.read()
                if not ok:
                    self.error = f"Camera {self.index} stopped producing frames."
                    break
                sequence += 1
                monotonic_now = time.monotonic()
                packet = FramePacket(sequence, frame, monotonic_now, monotonic_now,
                                     source_frame_index=sequence - 1,
                                     wall_time_utc=datetime.now(timezone.utc))
                self.store.publish(packet)
                measured_frames += 1
                elapsed = time.perf_counter() - measured_at
                if elapsed >= 1.0:
                    self.capture_fps = measured_frames / elapsed
                    measured_at, measured_frames = time.perf_counter(), 0
                self._ready.set()
        finally:
            capture.release()
            self.ended = True


class VideoFileSource(FrameSource):
    def __init__(self, path: Path, source_fps_override: float | None = None):
        super().__init__()
        self.path = Path(path)
        self.source_fps_override = source_fps_override
        self.playback_drift_ms = 0.0
        self.playback_elapsed_s = 0.0

    def _run(self):
        if not self.path.exists():
            self.error = f"Video file does not exist: {self.path}"
            self._ready.set()
            return
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            self.error = f"Video decoder cannot open: {self.path}"
            self._ready.set()
            return
        metadata_fps = float(capture.get(cv2.CAP_PROP_FPS))
        fps = self.source_fps_override or metadata_fps
        if not (fps > 0 and fps < 1000):
            self.error = "Invalid/unknown video FPS; provide --source-fps."
            self._ready.set()
            capture.release()
            return
        frame_count_value = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_count = frame_count_value if frame_count_value > 0 else None
        self.metadata = SourceMetadata(
            SourceKind.VIDEO_FILE, str(self.path),
            int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps, frame_count, (frame_count / fps) if frame_count else None,
            ("frame-index/explicit FPS" if self.source_fps_override
             else "video POS_MSEC with frame-index/FPS fallback"),
        )
        playback_started = time.monotonic()
        previous_source_time = -1.0
        frame_index = 0
        measured_at, measured_frames = time.perf_counter(), 0
        try:
            while not self._stop.is_set():
                ok, frame = capture.read()
                if not ok:
                    self.ended = True
                    break
                pos_seconds = float(capture.get(cv2.CAP_PROP_POS_MSEC)) / 1000.0
                fallback = frame_index / fps
                if frame_index == 0:
                    source_time = 0.0
                elif (not self.source_fps_override and pos_seconds > previous_source_time
                      and abs(pos_seconds - fallback) <= max(1.0, 5.0 / fps)):
                    source_time = pos_seconds
                else:
                    source_time = fallback
                desired_monotonic = playback_started + source_time
                remaining = desired_monotonic - time.monotonic()
                if remaining > 0:
                    self._stop.wait(remaining)
                    if self._stop.is_set():
                        break
                captured_monotonic = time.monotonic()
                self.playback_drift_ms = (captured_monotonic - desired_monotonic) * 1000.0
                packet = FramePacket(frame_index + 1, frame, source_time, captured_monotonic,
                                     source_frame_index=frame_index, wall_time_utc=None)
                self.store.publish(packet)
                previous_source_time = source_time
                frame_index += 1
                measured_frames += 1
                elapsed = time.perf_counter() - measured_at
                if elapsed >= 1.0:
                    self.capture_fps = measured_frames / elapsed
                    measured_at, measured_frames = time.perf_counter(), 0
                self._ready.set()
        finally:
            self.playback_elapsed_s = time.monotonic() - playback_started
            capture.release()
            self.ended = True


def create_source(spec: SourceSpec, source_fps_override: float | None = None) -> FrameSource:
    if spec.kind == SourceKind.CAMERA:
        return CameraSource(int(spec.value))
    if spec.kind == SourceKind.VIDEO_FILE:
        return VideoFileSource(Path(spec.value), source_fps_override)
    raise NotImplementedError(f"Source kind is reserved but not implemented: {spec.kind.value}")
