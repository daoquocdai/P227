"""Capture and scheduling primitives for the realtime Vision pipeline."""

from __future__ import annotations

import threading
import time


class LatestFrameStore:
    """A bounded-by-design slot: publishing replaces the previous frame."""

    def __init__(self):
        self._condition = threading.Condition()
        self._snapshot = None
        self.published = 0

    def publish(self, packet):
        with self._condition:
            self.published += 1
            self._snapshot = packet
            self._condition.notify_all()

    def latest(self):
        with self._condition:
            return self._snapshot

    def wait_newer(self, sequence, timeout):
        with self._condition:
            self._condition.wait_for(
                lambda: self._snapshot is not None and self._snapshot.sequence > sequence,
                timeout=timeout,
            )
            return self._snapshot


class FixedRateScheduler:
    def __init__(self, target_fps=15.0):
        if target_fps <= 0:
            raise ValueError("target_fps must be positive")
        self.target_fps = float(target_fps)
        self.interval = 1.0 / self.target_fps
        self.next_deadline = time.perf_counter()
        self.deadline_miss_count = 0
        self.cycles = 0

    def wait(self):
        now = time.perf_counter()
        remaining = self.next_deadline - now
        if remaining > 0:
            time.sleep(remaining)
            now = time.perf_counter()
        elif self.cycles and now - self.next_deadline > self.interval * 0.1:
            self.deadline_miss_count += 1
        self.cycles += 1
        self.next_deadline = max(self.next_deadline + self.interval, now)
