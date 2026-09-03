import multiprocessing as mp
import pickle
import sys
import tempfile
import threading
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sda_vision import (
    IdentityGalleryEntry,
    IdentityGallerySnapshot,
    VisionCallbacks,
    VisionDetection,
    VisionEvent,
    VisionFrameResult,
    VisionSession,
    VisionSessionConfig,
)
from sda_vision.action_labels import ACTION_CLASSES
from sda_vision.cli import parse_args
from sda_vision.contracts import FrameTransform, effective_inference_dimensions
from sda_vision.runtime.identity import IdentityResult, IdentityState, _replace_latest
from sda_vision.runtime.timing import PoseSample


class PublicImportTests(unittest.TestCase):
    def test_gallery_embedding_is_defensively_copied_and_read_only(self):
        source = np.ones(4, dtype=np.float32)
        entry = IdentityGalleryEntry("person", "Name", source)
        source[0] = 9
        self.assertEqual(entry.embedding[0], 1)
        self.assertFalse(entry.embedding.flags.writeable)
        with self.assertRaises(ValueError):
            entry.embedding[0] = 2

    def test_post_fall_stability_emits_once_and_movement_clears(self):
        session = VisionSession.__new__(VisionSession)
        session.config = SimpleNamespace(raw_classifier=False)
        still = np.zeros((25, 3), dtype=np.float32)
        still[2, 0] = 1.0  # non-zero torso scale
        session.pose_samples = deque([PoseSample(0.0, still.copy())])
        session.pending_event = {
            "started_source_time_s": 0.0, "state": "FALL_DETECTED",
            "anchor_kpts": None, "next_check_source_time_s": 0.0, "conf": 0.9,
        }
        session.current_action = ""
        session.action_color = (0, 0, 0)
        emitted = []
        session.emit_event = lambda event_type, confidence: emitted.append((event_type, confidence))

        for timestamp in (2.0, 3.0, 5.0, 7.0, 9.0, 11.0):
            session.pose_samples.append(PoseSample(timestamp, still.copy()))
            session.detect_fall(timestamp)
        self.assertEqual(session.pending_event["state"], "ALERT")
        self.assertEqual(emitted, [("FALL_CONFIRMED", 0.9)])

        moved = still.copy()
        moved[5, 0] = 1.0
        session.pose_samples.append(PoseSample(13.0, moved))
        session.detect_fall(13.0)
        self.assertIsNone(session.pending_event)
        self.assertEqual(len(emitted), 1)

    def test_small_public_api_imports(self):
        self.assertTrue(VisionSession)
        self.assertTrue(VisionSessionConfig)
        self.assertTrue(VisionCallbacks)
        self.assertTrue(VisionFrameResult)
        self.assertTrue(VisionEvent)
        self.assertTrue(VisionDetection)

    def test_identity_tuning_defaults_are_serializable_and_disabled(self):
        config = VisionSessionConfig()
        restored = pickle.loads(pickle.dumps(config))
        self.assertEqual(restored.identity_process_priority, "normal")
        self.assertIsNone(restored.identity_cpu_affinity)
        self.assertEqual(restored.num_poses, 1)
        self.assertEqual((restored.input_width, restored.input_height), (1280, 720))

    def test_core_has_no_backend_dependency(self):
        package = ROOT / "sda_vision"
        core_files = [package / "session.py", package / "contracts.py",
                      package / "config.py", package / "callbacks.py"]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in core_files)
        self.assertNotIn("from src", combined)
        self.assertNotIn("fastapi", combined.lower())
        self.assertNotIn("sqlite", combined.lower())


class ContractTests(unittest.TestCase):
    def test_deployed_five_class_labels_are_exact_and_stable(self):
        self.assertEqual(
            [(item.class_id, item.name, item.label) for item in ACTION_CLASSES.values()],
            [
                (0, "fall", "Ngã"),
                (1, "standing", "Đứng"),
                (2, "bending", "Cúi"),
                (3, "sitting", "Ngồi"),
                (4, "lying", "Nằm"),
            ],
        )

    def test_padded_inference_bbox_maps_to_source_pixels(self):
        transform = FrameTransform(1920, 1080)
        self.assertEqual(transform.bbox_to_source((0, 0, 1280, 720)), (0, 0, 1920, 1080))
        portrait_size = effective_inference_dimensions(480, 640)
        portrait = FrameTransform(480, 640, *portrait_size)
        self.assertEqual(portrait.bbox_to_source((0, 160, 720, 1120)), (0, 0, 480, 640))

    def test_effective_inference_dimensions_follow_source_orientation(self):
        self.assertEqual(effective_inference_dimensions(1920, 1080), (1280, 720))
        self.assertEqual(effective_inference_dimensions(1080, 1920), (720, 1280))

    def test_portrait_bbox_maps_back_to_source_pixels(self):
        width, height = effective_inference_dimensions(1080, 1920)
        transform = FrameTransform(1080, 1920, width, height)
        self.assertEqual(
            transform.bbox_to_source((72, 128, 648, 1152)),
            (108, 192, 972, 1728),
        )

    def test_canceled_pending_fall_clears_stale_action_metadata(self):
        session = VisionSession.__new__(VisionSession)
        session.config = SimpleNamespace(raw_classifier=False, source_epoch=0)
        moved = np.zeros((25, 3), dtype=np.float32)
        moved[2, 0] = 1.0
        session.pose_samples_by_track = {7: deque([PoseSample(2.0, moved)])}
        session.pending_events_by_track = {7: {
            "started_source_time_s": 0.0,
            "state": "WARNING_PENDING",
            "anchor_kpts": np.zeros((25, 3), dtype=np.float32),
            "next_check_source_time_s": 1.0,
            "conf": 0.9,
        }}
        session.current_action_by_track = {7: "Phat hien nga"}
        session.action_color_by_track = {7: (0, 0, 255)}
        session.action_class_by_track = {7: (ACTION_CLASSES[0], 0.9)}
        session._pending_fall_diagnostics = []
        session.log_level = "error"

        session.detect_fall_for_track(2.0, 7)

        self.assertIsNone(session.pending_events_by_track[7])
        self.assertEqual(session.current_action_by_track[7], "Binh thuong")
        self.assertNotIn(7, session.action_class_by_track)

    def test_configurable_frame_transform_preserves_aspect_ratio(self):
        full_hd = FrameTransform(1920, 1080, 1280, 720)
        self.assertEqual((full_hd.scale, full_hd.padding), (2 / 3, (0, 0)))
        four_three = FrameTransform(640, 480, 1280, 720)
        self.assertEqual((four_three.scale, four_three.padding), (1.5, (160, 0)))
        reduced = FrameTransform(1280, 960, 960, 540)
        self.assertEqual((reduced.scale, reduced.padding), (0.5625, (120, 0)))

    def test_core_emits_structured_event(self):
        emitted = []
        session = VisionSession.__new__(VisionSession)
        session.config = VisionSessionConfig(camera_id="cam-1", camera_location="Hall")
        session.callbacks = VisionCallbacks(on_event=emitted.append)
        session.last_sent_time = {}
        session._event_frame_sequence = 7
        session._event_source_time_s = 1.25
        session._latest_detection = VisionDetection("person", bbox=(1, 2, 3, 4))
        session._pending_generated_events = []
        session.emit_event("FALL_CONFIRMED", 0.8)
        self.assertEqual(len(emitted), 1)
        self.assertIsInstance(emitted[0], VisionEvent)
        self.assertEqual((emitted[0].frame_sequence, emitted[0].source_time_s), (7, 1.25))
        self.assertEqual(emitted[0].person_bbox, (1, 2, 3, 4))


class CliTests(unittest.TestCase):
    def test_realtime_arguments_map_without_starting_runtime(self):
        args = parse_args(["--source", "1", "--identity", "off", "--preview", "none"])
        self.assertEqual(args.source, "1")
        self.assertEqual(args.identity, "off")
        self.assertEqual(args.preview, "none")


class ShutdownTests(unittest.TestCase):
    class Resource:
        def __init__(self):
            self.calls = 0
            self.ended = False
            self.error = None
            self.capture_fps = 0.0
            self.source_epoch = 0
        def stop(self):
            self.calls += 1

    class PoseResource(Resource):
        def close(self):
            self.calls += 1

    def test_split_cleanup_keeps_source_alive_until_source_shutdown(self):
        source = self.Resource()
        identity = self.Resource()
        pose = self.PoseResource()
        action = self.PoseResource()
        session = VisionSession.__new__(VisionSession)
        session._vision_stop_requested = False
        session.frame_source = source
        session.identity_stage = identity
        session.pose_model = pose
        session.action_model = action
        session._last_identity_queue = {}

        session.shutdown_vision()
        session.shutdown_vision()
        self.assertEqual((source.calls, identity.calls, pose.calls, action.calls), (0, 1, 1, 1))

        session.stop_source()
        session.stop_source()
        self.assertEqual(source.calls, 1)

        session.shutdown()
        session.shutdown()
        self.assertEqual((source.calls, identity.calls, pose.calls, action.calls), (1, 1, 1, 1))

    def test_identity_worker_restarts_once_after_vision_lifecycle_shutdown(self):
        stages = []

        class IdentityResource(self.Resource):
            def __init__(self, *args, **kwargs):
                super().__init__()
                self.start_calls = 0
                stages.append(self)

            def start(self):
                self.start_calls += 1

        class ActionResource:
            def close(self):
                pass

        face_spec = SimpleNamespace(providers=("CPUExecutionProvider",), device="CPU")
        with (
            patch("sda_vision.session.resolve_face_providers", return_value=face_spec),
            patch("sda_vision.session.face_stage_spec", return_value=object()),
            patch("sda_vision.session.IdentityStage", IdentityResource),
        ):
            session = VisionSession(VisionSessionConfig(identity_enabled=True, preview="none"))
            session.action_model = ActionResource()

            session.init_models()
            session.init_models()
            first = session.identity_stage
            self.assertEqual(len(stages), 1)
            self.assertEqual(first.start_calls, 1)

            session.shutdown_vision()
            self.assertEqual(first.calls, 1)
            self.assertIsNone(session.identity_stage)
            self.assertFalse(session._identity_start_attempted)

            session.action_model = ActionResource()
            session.init_models()
            session.init_models()
            second = session.identity_stage
            self.assertEqual(len(stages), 2)
            self.assertIsNot(second, first)
            self.assertEqual(second.start_calls, 1)

            session.shutdown_vision()


class SessionControlTests(unittest.TestCase):
    def test_identity_start_failure_is_isolated_and_not_retried(self):
        session = VisionSession(VisionSessionConfig(identity_enabled=True, preview="none"))
        session.action_model = object()
        with (
            patch(
                "sda_vision.session.resolve_face_providers",
                return_value=SimpleNamespace(providers=("CPUExecutionProvider",), device="CPU"),
            ),
            patch("sda_vision.session.face_stage_spec", return_value=object()),
            patch("sda_vision.session.IdentityStage", side_effect=RuntimeError("model missing")) as stage,
        ):
            session._start_identity_stage()
            session._start_identity_stage()
        self.assertEqual(stage.call_count, 1)
        self.assertIsNone(session.identity_stage)
        self.assertEqual(session.face_startup_error, "model missing")
        self.assertEqual(session.face_stage.backend, "UNAVAILABLE")

    def test_disabling_vision_stops_identity_worker(self):
        session = VisionSession(VisionSessionConfig(identity_enabled=True, preview="none"))
        identity = self.FakeIdentity(IdentityResult())
        session.identity_stage = identity
        session.inference_enabled = True
        session.action_model = object()
        session._reset_temporal_state = lambda: None
        session.set_inference_enabled(False)
        self.assertTrue(identity.stopped)
        self.assertIsNone(session.identity_stage)
        self.assertFalse(session._identity_start_attempted)

    def test_vision_off_keeps_source_rate_callback_active(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 20, (64, 48))
            self.assertTrue(writer.isOpened())
            for index in range(11):
                writer.write(np.full((48, 64, 3), index, dtype=np.uint8))
            writer.release()
            received = []
            session = VisionSession(
                VisionSessionConfig(source=str(path), inference_enabled=False, preview="none"),
                VisionCallbacks(on_source_frame=received.append),
            )
            session.run()
            self.assertEqual(len(received), 11)
            self.assertEqual(session.frame_count, 0)

    def test_reenable_clears_temporal_state(self):
        session = VisionSession(VisionSessionConfig(inference_enabled=False, preview="none"))
        session.pose_samples = deque([PoseSample(1.0, np.ones((25, 3)))])
        session.pending_event = {"state": "WARNING"}
        session.set_inference_enabled(True)
        self.assertEqual(len(session.pose_samples), 0)
        self.assertIsNone(session.pending_event)

    def test_enabling_identity_on_initialized_session_starts_worker(self):
        session = VisionSession.__new__(VisionSession)
        session._control_lock = threading.RLock()
        session.identity_enabled = False
        session.identity_stage = None
        session.action_model = object()
        session.config = SimpleNamespace(identity_enabled=False)
        session._last_identity_event_timestamp = 1.0
        session._latest_detection = object()
        started = []
        session._start_identity_stage = lambda: started.append(True)
        session.set_identity_enabled(True)
        self.assertTrue(session.identity_enabled)
        self.assertEqual(started, [True])

    def test_reenabling_inference_restarts_desired_identity_worker(self):
        session = VisionSession.__new__(VisionSession)
        session._control_lock = threading.RLock()
        session.inference_enabled = False
        session.identity_enabled = True
        session.identity_stage = None
        session.action_model = object()
        session.config = SimpleNamespace(inference_enabled=False)
        session._reset_temporal_state = lambda: None
        started = []
        session._start_identity_stage = lambda: started.append(True)
        session.set_inference_enabled(True)
        self.assertEqual(started, [True])

    def test_source_epoch_reset_clears_fall_pending_state(self):
        session = VisionSession(VisionSessionConfig(inference_enabled=False, preview="none"))
        session.pose_samples.append(PoseSample(1.0, np.ones((25, 3))))
        session.pending_event = {"state": "FALL_CONFIRMED"}
        session._reset_temporal_state()
        self.assertFalse(session.pose_samples)
        self.assertIsNone(session.pending_event)

    class FakeIdentity:
        frames_processed = 1
        def __init__(self, result):
            self.result = result
            self.stopped = False
            self.reset_calls = 0
            self.association_id = 1
        def submit(self, *_args, **_kwargs):
            return True
        def poll(self):
            return self.result
        def reset(self):
            self.reset_calls += 1
            self.result = IdentityResult()
            self.association_id = None
        def update_presence(self, bbox, now=None):
            if bbox is None and now >= 2.0:
                self.reset()
        def stop(self):
            self.stopped = True

    def _face_session(self, result):
        session = VisionSession.__new__(VisionSession)
        session.identity_enabled = True
        session.identity_stage = self.FakeIdentity(result)
        session._control_lock = threading.RLock()
        session._frame_transform = FrameTransform(1280, 720)
        session.log_level = "error"
        session.current_identity_ms = None
        session._last_identity_event_timestamp = result.timestamp
        session._latest_detection = None
        session._current_packet = None
        session._identity_track_id = None
        session.yolo_cached_boxes = []
        session.orig_w = 1280
        session.orig_h = 720
        return session

    def test_identity_state_follows_tracker_id(self):
        result = IdentityResult(IdentityState.LOCKED_KNOWN, "Dai", 0.9)
        session = self._face_session(result)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)

        first = session.process_person(frame, 100, 100, 500, 600, 7)
        session.process_person(frame, 102, 102, 502, 602, 7)
        self.assertEqual(session.identity_stage.reset_calls, 0)
        self.assertEqual(first.association_id, 7)

        replacement = session.process_person(frame, 100, 100, 500, 600, 8)
        self.assertEqual(session.identity_stage.reset_calls, 1)
        self.assertEqual(session._identity_track_id, 8)
        self.assertEqual(replacement.association_id, 8)

    def test_long_absence_clears_identity_track(self):
        session = self._face_session(IdentityResult(IdentityState.LOCKED_UNKNOWN))
        session._identity_track_id = 4
        session._mark_identity_absent(2.0)
        self.assertEqual(session.identity_stage.reset_calls, 1)
        self.assertIsNone(session._identity_track_id)
        self.assertEqual(session._last_identity_event_timestamp, 0.0)

        detection = session.process_person(
            np.zeros((720, 1280, 3), dtype=np.uint8), 100, 100, 500, 600, 5
        )
        self.assertIsNotNone(detection)
        self.assertEqual(detection.association_id, 5)

    def test_exact_face_bbox_is_mapped_only_for_matching_frame(self):
        result = IdentityResult(
            IdentityState.LOCKED_KNOWN, "Dai", 0.9, 1.0, (100, 100, 500, 600),
            10.0, 2.0, 7, (10, 20, 110, 120), 7)
        session = self._face_session(result)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        session.process_person(frame, 100, 100, 500, 600, None,
                               frame_sequence=7, source_time_s=2.0)
        self.assertEqual(session._latest_detection.face_bbox, (110, 120, 210, 220))

        stale = IdentityResult(
            IdentityState.LOCKED_KNOWN, "Dai", 0.9, 1.0, (100, 100, 500, 600),
            10.0, 2.0, 6, (10, 20, 110, 120), 6)
        session = self._face_session(stale)
        session.process_person(frame, 100, 100, 500, 600, None,
                               frame_sequence=7, source_time_s=2.0)
        self.assertIsNone(session._latest_detection.face_bbox)


class WindowsSpawnImportTests(unittest.TestCase):
    def test_package_target_is_spawn_importable(self):
        context = mp.get_context("spawn")
        output = context.Queue(maxsize=1)
        process = context.Process(target=_replace_latest, args=(output, {"ok": True}))
        process.start()
        process.join(10)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual(output.get(timeout=1), {"ok": True})
        output.close()

    def test_supplied_gallery_contract_survives_windows_spawn(self):
        context = mp.get_context("spawn")
        output = context.Queue(maxsize=1)
        snapshot = IdentityGallerySnapshot(
            7, (IdentityGalleryEntry("person-7", "Dai", np.ones(512)),))
        process = context.Process(target=_replace_latest, args=(output, snapshot))
        process.start()
        process.join(10)
        received = output.get(timeout=1)
        self.assertEqual(process.exitcode, 0)
        self.assertEqual((received.version, received.entries[0].person_id), (7, "person-7"))
        output.close()


if __name__ == "__main__":
    unittest.main()
