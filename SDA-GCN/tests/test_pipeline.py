import queue
import threading
import time
import unittest

import numpy as np

from runtime.identity import IdentityResult, IdentityStage, IdentityState
from runtime.pipeline import FixedRateScheduler, LatestFrameStore
from runtime.source import FramePacket


class LatestFrameTests(unittest.TestCase):
    def test_slow_consumer_observes_newest_frame_without_backlog(self):
        store = LatestFrameStore()
        for value in range(100):
            store.publish(FramePacket(value + 1, value, value / 10, value / 10))
        snapshot = store.latest()
        self.assertEqual(snapshot.sequence, 100)
        self.assertEqual(snapshot.frame, 99)


class IdentityStateTests(unittest.TestCase):
    def make_stage(self):
        stage = IdentityStage.__new__(IdentityStage)
        stage._inputs = queue.Queue(maxsize=1)
        stage._results = queue.Queue(maxsize=1)
        stage._status = queue.Queue(maxsize=1)
        stage._ready = threading.Event()
        stage.interval = 0.5
        stage.unknown_retry = 1.0
        stage.locked_unknown_retry = 15.0
        stage.max_unknown_attempts = 3
        stage.absent_timeout = 1.5
        stage.result = IdentityResult()
        stage.failed_attempts = 0
        stage.last_attempt_at = 0.0
        stage.last_present_at = 0.0
        stage.association_bbox = None
        stage.frames_submitted = 0
        stage.frames_processed = 0
        stage.frames_dropped = 0
        stage.started_at = time.monotonic()
        stage.gallery_status = None
        return stage

    def test_locked_known_never_periodically_retries(self):
        stage = self.make_stage()
        stage.result = IdentityResult(IdentityState.LOCKED_KNOWN, "Alice", 0.9)
        submitted = stage.submit(np.zeros((2, 2, 3)), (0, 0, 10, 10), now=100.0)
        self.assertFalse(submitted)
        self.assertTrue(stage._inputs.empty())

    def test_not_ready_does_not_submit_or_increment_metrics(self):
        stage = self.make_stage()
        submitted = stage.submit(np.zeros((2, 2, 3)), (0, 0, 10, 10), now=10.0)
        self.assertFalse(submitted)
        self.assertEqual((stage.frames_submitted, stage.frames_dropped), (0, 0))

    def test_unknown_retries_cool_down_then_locks(self):
        stage = self.make_stage()
        for attempt in range(3):
            stage._results.put({"known": False, "confidence": 0.1, "timestamp": attempt,
                                "bbox": (0, 0, 10, 10), "inference_ms": 10.0})
            stage.poll()
        self.assertEqual(stage.result.state, IdentityState.LOCKED_UNKNOWN)
        self.assertFalse(stage._due(10.0))
        self.assertTrue(stage._due(20.0))

    def test_bbox_association_change_invalidates_lock(self):
        stage = self.make_stage()
        stage.result = IdentityResult(IdentityState.LOCKED_KNOWN, "Alice", 0.9)
        stage.association_bbox = (0, 0, 10, 10)
        stage.update_presence((100, 100, 110, 110), now=5.0)
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)

    def test_result_from_old_bbox_cannot_lock_new_person(self):
        stage = self.make_stage()
        stage.association_bbox = (100, 100, 110, 110)
        stage._results.put({"known": True, "name": "Alice", "confidence": 0.9,
                            "timestamp": 2.0, "bbox": (0, 0, 10, 10), "inference_ms": 10.0})
        stage.poll()
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)


class SchedulerIsolationTests(unittest.TestCase):
    def test_slow_identity_work_does_not_block_scheduler(self):
        thread = threading.Thread(target=lambda: time.sleep(0.5), daemon=True)
        thread.start()
        scheduler = FixedRateScheduler(20)
        started = time.perf_counter()
        cycles = 0
        while time.perf_counter() - started < 0.3:
            scheduler.wait()
            cycles += 1
        self.assertGreaterEqual(cycles, 6)
        self.assertTrue(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
