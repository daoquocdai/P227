import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from runtime.source import SourceKind, StreamSource, VideoFileSource, parse_source
from runtime.timing import MediaPipeTimestampAdapter, PoseSample, source_span_s


class SourceParsingTests(unittest.TestCase):
    def test_numeric_source_is_camera(self):
        spec = parse_source("2")
        self.assertEqual((spec.kind, spec.value), (SourceKind.CAMERA, 2))

    def test_existing_numeric_filename_has_path_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "0"
            path.touch()
            self.assertEqual(parse_source(str(path)).kind, SourceKind.VIDEO_FILE)

    def test_missing_video_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_source("definitely_missing_video.mp4")


class ClockTests(unittest.TestCase):
    def test_mediapipe_timestamp_is_strictly_monotonic(self):
        adapter = MediaPipeTimestampAdapter()
        values = [adapter.convert(value) for value in (0.0, 0.0, 0.001, 0.0005, 1.0)]
        self.assertTrue(all(right > left for left, right in zip(values, values[1:])))

    def test_mediapipe_timestamp_remains_monotonic_across_epoch_reset(self):
        adapter = MediaPipeTimestampAdapter()
        values = [adapter.convert(0.0, 0), adapter.convert(1.0, 0),
                  adapter.convert(0.0, 1), adapter.convert(0.033, 1)]
        self.assertTrue(all(right > left for left, right in zip(values, values[1:])))

    def test_source_window_ignores_wall_clock_jump(self):
        samples = [PoseSample(10.0, None)]
        with patch("time.time", side_effect=[1.0, 999999.0]):
            self.assertEqual(source_span_s(samples, 12.25), 2.25)
            self.assertEqual(source_span_s(samples, 12.25), 2.25)


class VideoPlaybackTests(unittest.TestCase):
    @staticmethod
    def _write_video(path, fps=20, frames=21):
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
        if not writer.isOpened():
            raise RuntimeError("test video writer unavailable")
        for index in range(frames):
            writer.write(np.full((48, 64, 3), index, dtype=np.uint8))
        writer.release()

    def _run_video(self, fps):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "short.avi"
            writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (64, 48))
            self.assertTrue(writer.isOpened())
            for index in range(fps + 1):
                writer.write(np.full((48, 64, 3), index, dtype=np.uint8))
            writer.release()

            source = VideoFileSource(path)
            started = time.monotonic()
            source.start()
            observed = []
            sequence = 0
            while not source.ended or (source.store.latest() and source.store.latest().sequence > sequence):
                packet = source.store.wait_newer(sequence, 0.08)
                if packet and packet.sequence > sequence:
                    observed.append(packet)
                    sequence = packet.sequence
                    time.sleep(1.0 / 15.0)
            elapsed = time.monotonic() - started
            source.stop()

            self.assertTrue(source.ended)
            self.assertGreaterEqual(elapsed, 0.9)
            self.assertLess(elapsed, 1.5)
            self.assertEqual(observed[-1].source_frame_index, fps)
            self.assertAlmostEqual(observed[-1].source_time_s, 1.0, places=2)
            self.assertTrue(all(b.source_time_s > a.source_time_s for a, b in zip(observed, observed[1:])))
            return observed

    def test_realtime_pacing_latest_sampling_and_clean_eof(self):
        for fps, expected_step in ((30, 2), (60, 4)):
            with self.subTest(source_fps=fps):
                observed = self._run_video(fps)
                steps = [b.source_frame_index - a.source_frame_index
                         for a, b in zip(observed[2:], observed[3:])]
                self.assertGreaterEqual(len(observed), 12)
                self.assertLessEqual(len(observed), 18)
                self.assertAlmostEqual(float(np.median(steps)), expected_step, delta=1.0)

    def test_source_callback_receives_every_published_frame(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "callback.avi"
            self._write_video(path, 20, 11)
            received = []
            source = VideoFileSource(path, on_frame=received.append)
            source.start()
            while not source.ended:
                time.sleep(0.02)
            source.stop()
            self.assertEqual(len(received), 11)
            self.assertEqual([packet.sequence for packet in received], list(range(1, 12)))

    def test_video_loop_increments_epoch_and_resets_frame_index(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "loop.avi"
            self._write_video(path, 20, 4)
            received = []
            source = VideoFileSource(path, loop=True, on_frame=received.append)
            source.start()
            deadline = time.monotonic() + 2
            while source.source_epoch < 1 and time.monotonic() < deadline:
                time.sleep(0.01)
            source.stop()
            first_new_epoch = next(packet for packet in received if packet.source_epoch == 1)
            self.assertEqual(first_new_epoch.source_frame_index, 0)
            self.assertEqual(first_new_epoch.source_time_s, 0.0)
            self.assertGreater(first_new_epoch.sequence, received[0].sequence)


class StreamSourceTests(unittest.TestCase):
    def test_reconnect_increments_epoch_and_keeps_sequence_monotonic(self):
        class Capture:
            def __init__(self): self.reads = 0
            def isOpened(self): return True
            def get(self, _key): return 64
            def read(self):
                self.reads += 1
                return ((True, np.zeros((2, 2, 3), np.uint8)) if self.reads == 1 else (False, None))
            def release(self): pass

        received = []
        source = None

        def receive(packet):
            received.append(packet)
            if len(received) == 2:
                source.request_stop()

        source = StreamSource("rtsp://user:secret@example.invalid/live", reconnect_delay=0.001,
                              on_frame=receive, initial_epoch=4)
        with patch("runtime.source.cv2.VideoCapture", side_effect=lambda _uri: Capture()):
            source.start()
            deadline = time.monotonic() + 1
            while len(received) < 2 and time.monotonic() < deadline:
                time.sleep(0.001)
            source.stop()
        self.assertEqual([packet.sequence for packet in received], [1, 2])
        self.assertEqual([packet.source_epoch for packet in received], [4, 5])
        self.assertEqual(source.metadata.name, "rtsp stream")


if __name__ == "__main__":
    unittest.main()
