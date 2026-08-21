"""Typed temporal packets and adapters shared by realtime entry points."""

from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass(frozen=True)
class PoseSubmission:
    source_time_s: float
    frame_sequence: int
    submitted_perf_counter_s: float
    frame: object
    source_frame_index: int | None = None
    wall_time_utc: object | None = None


@dataclass(frozen=True)
class PosePacket:
    source_time_s: float
    frame_sequence: int
    result: object
    callback_latency_ms: float
    frame: object
    source_frame_index: int | None = None
    wall_time_utc: object | None = None


@dataclass(frozen=True)
class PoseSample:
    source_time_s: float
    keypoints: object


class MediaPipeTimestampAdapter:
    def __init__(self):
        self.last_timestamp_ms = -1

    def convert(self, source_time_s: float) -> int:
        candidate = round(source_time_s * 1000.0)
        if candidate <= self.last_timestamp_ms:
            candidate = self.last_timestamp_ms + 1
        self.last_timestamp_ms = candidate
        return candidate


class LatestPoseStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._packet = None

    def publish(self, packet: PosePacket):
        with self._lock:
            self._packet = packet

    def latest(self):
        with self._lock:
            return self._packet


def source_span_s(samples, current_source_time_s: float) -> float:
    """Semantic window age, deliberately independent from all wall clocks."""
    return current_source_time_s - samples[0].source_time_s if samples else 0.0
