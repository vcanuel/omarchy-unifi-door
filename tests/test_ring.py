import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from door import ring  # noqa: E402


class ParseEvent(unittest.TestCase):
    def test_message(self):
        event = ring.parse_event(b'{"id":"a1","time":100,"event":"message","topic":"t","message":"Ring"}')
        self.assertEqual(event, {"id": "a1", "time": 100, "message": "Ring"})

    def test_keepalive_open_and_noise(self):
        for line in (b'{"id":"k","time":1,"event":"keepalive","topic":"t"}',
                     b'{"id":"o","time":1,"event":"open","topic":"t"}', b"", b"not json", b"[]"):
            self.assertIsNone(ring.parse_event(line))


class Fresh(unittest.TestCase):
    def test_recent_ring_counts_old_one_does_not(self):
        self.assertTrue(ring.is_fresh({"time": 1000}, now=1000 + ring.FRESH_SEC))
        self.assertFalse(ring.is_fresh({"time": 1000}, now=1001 + ring.FRESH_SEC))


class Topic(unittest.TestCase):
    def test_new_topics_are_long_and_distinct(self):
        a, b = ring.new_topic(), ring.new_topic()
        self.assertNotEqual(a, b)
        self.assertGreaterEqual(len(a), len("unifi-door-") + 20)

    def test_url(self):
        self.assertEqual(ring.topic_url({"topic": "abc"}), "https://ntfy.sh/abc")
        self.assertEqual(ring.topic_url({"server": "https://ntfy.example/", "topic": "abc"}), "https://ntfy.example/abc")


if __name__ == "__main__":
    unittest.main()
