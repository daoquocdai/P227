import multiprocessing as mp
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sda_vision import (VisionCallbacks, VisionDetection, VisionEvent,
                        VisionFrameResult, VisionSession, VisionSessionConfig)
from sda_vision.cli import parse_args
from sda_vision.contracts import FrameTransform
from sda_vision.runtime.identity import _replace_latest


class PublicImportTests(unittest.TestCase):
    def test_small_public_api_imports(self):
        self.assertTrue(VisionSession)
        self.assertTrue(VisionSessionConfig)
        self.assertTrue(VisionCallbacks)
        self.assertTrue(VisionFrameResult)
        self.assertTrue(VisionEvent)
        self.assertTrue(VisionDetection)

    def test_core_has_no_backend_dependency(self):
        package = ROOT / "sda_vision"
        core_files = [package / "session.py", package / "contracts.py",
                      package / "config.py", package / "callbacks.py"]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in core_files)
        self.assertNotIn("from src", combined)
        self.assertNotIn("fastapi", combined.lower())
        self.assertNotIn("sqlite", combined.lower())


class ContractTests(unittest.TestCase):
    def test_padded_inference_bbox_maps_to_source_pixels(self):
        transform = FrameTransform(1920, 1080)
        self.assertEqual(transform.bbox_to_source((0, 0, 1280, 720)), (0, 0, 1920, 1080))
        portrait = FrameTransform(480, 640)
        self.assertEqual(portrait.bbox_to_source((370, 0, 910, 720)), (0, 0, 480, 640))

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
        def stop(self):
            self.calls += 1

    class PoseResource(Resource):
        def close(self):
            self.calls += 1

    def test_shutdown_is_idempotent(self):
        source = self.Resource()
        identity = self.Resource()
        pose = self.PoseResource()
        session = VisionSession.__new__(VisionSession)
        session._stop_requested = False
        session.frame_source = source
        session.identity_stage = identity
        session.pose_model = pose
        session.shutdown()
        session.shutdown()
        self.assertEqual((source.calls, identity.calls, pose.calls), (1, 1, 1))


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


if __name__ == "__main__":
    unittest.main()
