import unittest

from sda_vision.tracker import SimpleTracker


class SimpleTrackerTests(unittest.TestCase):
    def test_first_valid_rect_registers_and_maps_to_input(self):
        tracker = SimpleTracker(max_disappeared=2, max_distance=50)
        tracked = tracker.update([(0, 0, 20, 20)])
        self.assertEqual(tracked, {0: 0})

    def test_short_disappearance_reacquires_same_id(self):
        tracker = SimpleTracker(max_disappeared=2, max_distance=50)
        first_id = next(iter(tracker.update([(0, 0, 20, 20)])))
        tracker.update([])
        tracked = tracker.update([(2, 2, 22, 22)])
        self.assertEqual(tracked, {first_id: 0})

    def test_long_disappearance_registers_new_id(self):
        tracker = SimpleTracker(max_disappeared=1, max_distance=50)
        first_id = next(iter(tracker.update([(0, 0, 20, 20)])))
        tracker.update([])
        tracker.update([])
        tracked = tracker.update([(0, 0, 20, 20)])
        self.assertNotIn(first_id, tracked)
        self.assertEqual(tracked, {1: 0})

    def test_valid_rect_never_returns_an_empty_mapping(self):
        tracker = SimpleTracker(max_disappeared=2, max_distance=10)
        tracker.update([(0, 0, 20, 20)])
        self.assertTrue(tracker.update([(100, 100, 120, 120)]))


if __name__ == "__main__":
    unittest.main()
