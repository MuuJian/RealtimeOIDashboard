import threading
import unittest
from unittest.mock import patch

from realtime_oi_dashboard.poller_health import PollerClock, RecentErrorLog


class RecentErrorLogTests(unittest.TestCase):
    def test_records_errors_and_discards_expired_events(self):
        stop_event = threading.Event()
        errors = RecentErrorLog(
            stop_event,
            max_events=2,
            retention_seconds=10,
        )

        with patch("realtime_oi_dashboard.poller_health.time.monotonic", return_value=100):
            self.assertTrue(errors.record("BTCUSDT", ValueError("first")))
        with patch("realtime_oi_dashboard.poller_health.time.monotonic", return_value=105):
            self.assertTrue(errors.record("ETHUSDT", ValueError("second")))
            self.assertEqual(
                errors.recent(),
                [
                    {"symbol": "BTCUSDT", "error": "first"},
                    {"symbol": "ETHUSDT", "error": "second"},
                ],
            )
        with patch("realtime_oi_dashboard.poller_health.time.monotonic", return_value=111):
            self.assertEqual(
                errors.recent(),
                [{"symbol": "ETHUSDT", "error": "second"}],
            )

    def test_refuses_new_errors_after_stop(self):
        stop_event = threading.Event()
        stop_event.set()
        errors = RecentErrorLog(stop_event)

        self.assertFalse(errors.record("BTCUSDT", ValueError("ignored")))
        self.assertEqual(errors.recent(), [])


class PollerClockTests(unittest.TestCase):
    def _clock(self):
        with (
            patch("realtime_oi_dashboard.poller_health.time.time", return_value=100),
            patch(
                "realtime_oi_dashboard.poller_health.time.monotonic",
                return_value=50,
            ),
        ):
            return PollerClock(
                row_max_age_seconds=900,
                clock_skew_seconds=5,
                discontinuity_tolerance_seconds=10,
            )

    def test_detects_wall_and_monotonic_clock_disagreement(self):
        clock = self._clock()

        self.assertFalse(clock.observe_discontinuity(wall_now=110, monotonic_now=60))
        self.assertTrue(clock.observe_discontinuity(wall_now=150, monotonic_now=61))

    def test_rows_require_recent_success_timestamp(self):
        clock = self._clock()

        self.assertTrue(clock.rows_are_stale(100))
        clock.mark_success(100)
        self.assertFalse(clock.rows_are_stale(1_000))
        self.assertTrue(clock.rows_are_stale(1_000.1))
        self.assertTrue(clock.rows_are_stale(94.9))
        clock.clear_success()
        self.assertTrue(clock.rows_are_stale(100))


if __name__ == "__main__":
    unittest.main()
