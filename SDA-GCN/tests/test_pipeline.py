import queue
import sys
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from runtime.pipeline import FixedRateScheduler, LatestFrameStore
from runtime.source import FramePacket
from sda_vision import IdentityGalleryEntry, IdentityGallerySnapshot, VisionEvent, VisionSession
from sda_vision.runtime import identity as identity_runtime
from sda_vision.runtime.identity import (
    IdentityResult,
    IdentityStage,
    IdentityState,
    _apply_process_isolation,
    validate_cpu_affinity,
    validate_process_priority,
)


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
        stage.interval = 0.3
        stage.unknown_retry = 1.0
        stage.locked_unknown_retry = 3.0
        stage.max_unknown_attempts = 3
        stage.absent_timeout = 1.5
        stage.result = IdentityResult()
        stage.failed_attempts = 0
        stage.last_attempt_at = 0.0
        stage.last_present_at = 0.0
        stage.association_bbox = None
        stage.association_id = None
        stage.association_generation = 0
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
                                "bbox": (0, 0, 10, 10), "inference_ms": 10.0,
                                "face_found": True})
            stage.poll()
        self.assertEqual(stage.result.state, IdentityState.LOCKED_UNKNOWN)
        stage.last_attempt_at = 10.0
        self.assertFalse(stage._due(12.9))
        self.assertTrue(stage._due(13.0))

    def test_no_face_is_inconclusive_and_never_locks_unknown(self):
        stage = self.make_stage()
        for attempt in range(3):
            stage._results.put({"known": False, "face_found": False,
                                "confidence": 0.0, "timestamp": attempt,
                                "bbox": (0, 0, 10, 10), "inference_ms": 10.0})
            stage.poll()
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)
        self.assertEqual(stage.failed_attempts, 0)
        self.assertFalse(stage.result.face_found)

    def test_no_face_preserves_existing_unknown_attempt_count(self):
        stage = self.make_stage()
        stage.failed_attempts = 1
        stage.result = IdentityResult(IdentityState.UNKNOWN, face_found=True)
        stage._results.put({"known": False, "face_found": False,
                            "confidence": 0.0, "timestamp": 2.0,
                            "bbox": (0, 0, 10, 10), "inference_ms": 10.0})
        stage.poll()
        self.assertEqual(stage.result.state, IdentityState.UNKNOWN)
        self.assertEqual(stage.failed_attempts, 1)

    def test_no_face_uses_fast_retry_even_after_unknown_lock(self):
        stage = self.make_stage()
        stage.result = IdentityResult(IdentityState.LOCKED_UNKNOWN, face_found=False)
        stage.last_attempt_at = 10.0
        self.assertFalse(stage._due(10.29))
        self.assertTrue(stage._due(10.3))

    def test_bbox_association_change_invalidates_lock(self):
        stage = self.make_stage()
        stage.result = IdentityResult(IdentityState.LOCKED_KNOWN, "Alice", 0.9)
        stage.association_bbox = (0, 0, 10, 10)
        stage.update_presence((100, 100, 110, 110), now=5.0)
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)

    def test_presence_association_is_stable_then_changes_after_absence(self):
        stage = self.make_stage()
        stage.update_presence((0, 0, 10, 10), now=1.0)
        first = stage.association_id
        stage.update_presence((1, 1, 11, 11), now=2.0)
        self.assertEqual(stage.association_id, first)
        stage.update_presence(None, now=4.0)
        self.assertIsNone(stage.association_id)
        stage.update_presence((1, 1, 11, 11), now=5.0)
        self.assertGreater(stage.association_id, first)

    def test_replacement_bbox_starts_new_association(self):
        stage = self.make_stage()
        stage.update_presence((0, 0, 10, 10), now=1.0)
        first = stage.association_id
        stage.update_presence((100, 100, 110, 110), now=2.0)
        self.assertGreater(stage.association_id, first)

    def test_result_from_old_bbox_cannot_lock_new_person(self):
        stage = self.make_stage()
        stage.association_bbox = (100, 100, 110, 110)
        stage._results.put({"known": True, "name": "Alice", "confidence": 0.9,
                            "timestamp": 2.0, "bbox": (0, 0, 10, 10), "inference_ms": 10.0})
        stage.poll()
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)

    def test_result_from_old_association_cannot_lock_new_person(self):
        stage = self.make_stage()
        stage.association_id = 2
        stage.association_generation = 2
        stage.association_bbox = (0, 0, 10, 10)
        stage._results.put({"known": True, "face_found": True, "person_id": "old",
                            "name": "Old", "confidence": 0.99, "timestamp": 2.0,
                            "bbox": (0, 0, 10, 10), "inference_ms": 10.0,
                            "association_id": 1})
        stage.poll()
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)

    def test_gallery_update_resets_locked_state_and_discards_stale_result(self):
        stage = self.make_stage()
        stage.gallery_mode = "supplied"
        stage.gallery_version = 1
        stage._gallery_updates = queue.Queue(maxsize=1)
        stage.result = IdentityResult(IdentityState.LOCKED_KNOWN, "Old", 0.9,
                                      gallery_version=1)
        snapshot = IdentityGallerySnapshot(
            2, (IdentityGalleryEntry("p2", "New", np.ones(4)),))
        stage.update_gallery(snapshot)
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)
        stage._results.put({"known": True, "person_id": "p1", "name": "Old",
                            "confidence": 0.99, "timestamp": 2.0,
                            "bbox": (0, 0, 10, 10), "inference_ms": 10.0,
                            "gallery_version": 1})
        stage.poll()
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)

    def test_gallery_update_queue_is_latest_only(self):
        stage = self.make_stage()
        stage.gallery_mode = "supplied"
        stage.gallery_version = 0
        stage._gallery_updates = queue.Queue(maxsize=1)
        stage.update_gallery(IdentityGallerySnapshot(1))
        stage.update_gallery(IdentityGallerySnapshot(2))
        stage.update_gallery(IdentityGallerySnapshot(3))
        stage.update_gallery(IdentityGallerySnapshot(4))
        self.assertEqual(stage._gallery_updates.get_nowait().version, 4)

    def test_gallery_update_resets_locked_unknown(self):
        stage = self.make_stage()
        stage.gallery_mode = "supplied"
        stage.gallery_version = 1
        stage._gallery_updates = queue.Queue(maxsize=1)
        stage.result = IdentityResult(IdentityState.LOCKED_UNKNOWN, gallery_version=1)
        stage.failed_attempts = 3
        stage.update_gallery(IdentityGallerySnapshot(2))
        self.assertEqual(stage.result.state, IdentityState.UNVERIFIED)
        self.assertEqual(stage.failed_attempts, 0)

    def test_session_gallery_update_preserves_fall_event_and_state(self):
        session = VisionSession.__new__(VisionSession)
        session._control_lock = threading.RLock()
        session.identity_gallery_mode = "supplied"
        session.identity_gallery_snapshot = IdentityGallerySnapshot(1)
        session.config = SimpleNamespace(identity_gallery_snapshot=None)
        session.identity_stage = None
        session._last_identity_event_timestamp = 5.0
        session._latest_detection = object()
        fall = VisionEvent("FALL_CONFIRMED", 0.9, 1, 1.0)
        identity = VisionEvent("PERSON_RECOGNIZED", 0.9, 1, 1.0)
        session._pending_generated_events = [fall, identity]
        session.fall_state = "CONFIRMED"
        session.update_identity_gallery(IdentityGallerySnapshot(2))
        self.assertEqual(session.fall_state, "CONFIRMED")
        self.assertEqual(session._pending_generated_events, [fall])


class IdentityIsolationTests(unittest.TestCase):
    def test_identity_responsiveness_defaults_keep_recognition_threshold(self):
        stage = IdentityStage(["CPUExecutionProvider"], ".", "identity-test-cache.npz")
        try:
            self.assertEqual(stage.interval, 0.3)
            self.assertEqual(stage.locked_unknown_retry, 3.0)
            self.assertEqual(stage.detection_threshold, 0.4)
            self.assertEqual(stage.recognition_threshold, 0.45)
        finally:
            stage._inputs.close()
            stage._results.close()
            stage._status.close()

    def test_identity_ipc_queues_remain_latest_only(self):
        stage = IdentityStage(
            ["CPUExecutionProvider"], ".", "identity-test-cache.npz")
        try:
            self.assertEqual(stage._inputs._maxsize, 1)
            self.assertEqual(stage._results._maxsize, 1)
        finally:
            stage._inputs.close()
            stage._results.close()
            stage._status.close()

    def test_priority_and_affinity_validation(self):
        self.assertEqual(validate_process_priority("below_normal"), "below_normal")
        self.assertEqual(validate_cpu_affinity([2, 2, 4], [0, 2, 4]), (2, 4))
        with self.assertRaises(ValueError):
            validate_process_priority("realtime")
        with self.assertRaises(ValueError):
            validate_cpu_affinity([9], [0, 1])

    def test_non_cpu_provider_does_not_apply_cpu_tuning(self):
        result = _apply_process_isolation(
            ["CUDAExecutionProvider", "CPUExecutionProvider"], "below_normal", (0,))
        self.assertFalse(result["isolation_applied"])
        self.assertIn("non-CPU", result["isolation_reason"])

    def test_cpu_affinity_is_applied_inside_target_process(self):
        class FakeProcess:
            affinity = [0, 1, 2, 3]
            priority = None

            def cpu_affinity(self, value=None):
                if value is not None:
                    self.affinity = list(value)
                return self.affinity

            def nice(self, value):
                self.priority = value

        process = FakeProcess()
        fake_psutil = SimpleNamespace(
            Process=lambda: process, BELOW_NORMAL_PRIORITY_CLASS=0x00004000)
        with patch.dict(sys.modules, {"psutil": fake_psutil}), patch.object(
                identity_runtime.os, "name", "nt"):
            result = _apply_process_isolation(
                ["CPUExecutionProvider"], "below_normal", (2, 3))
        self.assertTrue(result["isolation_applied"])
        self.assertEqual(result["effective_priority"], "below_normal")
        self.assertEqual(result["effective_affinity"], (2, 3))
        self.assertEqual(process.priority, fake_psutil.BELOW_NORMAL_PRIORITY_CLASS)

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
