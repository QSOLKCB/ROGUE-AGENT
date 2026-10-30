"""Additional in-process abuse cases without network services."""
from collections import deque
import unittest
from unittest.mock import patch

from habitat_api.server import RateLimiter


class RateLimitTests(unittest.TestCase):
    def test_fixed_window_and_expiry(self):
        limiter = RateLimiter(limit=2, window=10)
        with patch("habitat_api.server.time.monotonic", side_effect=[0, 1, 2, 11]):
            self.assertTrue(limiter.allow("127.0.0.1"))
            self.assertTrue(limiter.allow("127.0.0.1"))
            self.assertFalse(limiter.allow("127.0.0.1"))
            self.assertTrue(limiter.allow("127.0.0.1"))

    def test_peer_table_has_hard_bound(self):
        limiter = RateLimiter(limit=2, window=100, max_peers=2)
        self.assertTrue(limiter.allow("one"))
        self.assertTrue(limiter.allow("two"))
        self.assertFalse(limiter.allow("three"))
        self.assertEqual(len(limiter._times), 2)

    def test_invalid_rate_settings_fail_closed(self):
        for kwargs in ({"limit":0}, {"window":0}, {"max_peers":0}):
            with self.assertRaises(ValueError):
                RateLimiter(**kwargs)

if __name__ == "__main__":
    unittest.main()
