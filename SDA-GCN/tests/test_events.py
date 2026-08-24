import unittest

from runtime.events import EventSender


class EventSenderTests(unittest.TestCase):
    def test_standalone_sender_has_no_worker_and_drops_without_queueing(self):
        sender = EventSender()
        sender.enqueue({"event": "fall"})
        self.assertFalse(sender.enabled)
        self.assertIsNone(sender._thread)
        self.assertTrue(sender._queue.empty())
        sender.close()


if __name__ == "__main__":
    unittest.main()
