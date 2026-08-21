import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from runtime.source import SourceKind, VideoFileSource, parse_source
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

    def test_source_window_ignores_wall_clock_jump(self):
        samples = [PoseSample(10.0, None)]
        with patch("time.time", side_effect=[1.0, 999999.0]):
            self.assertEqual(source_span_s(samples, 12.25), 2.25)
            self.assertEqual(source_span_s(samples, 12.25), 2.25)


class VideoPlaybackTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
