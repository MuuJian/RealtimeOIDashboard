import unittest

from realtime_oi_dashboard.domain.cvd.model import (
    BUCKET_COUNT,
    MINUTE_MS,
    SymbolCvdWindow,
)
from realtime_oi_dashboard.application.cvd.presenter import _service_health


class SymbolCvdWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = SymbolCvdWindow("BTCUSDT")
        self.window.set_connected(True)

    def update(self, minute, quote, buy, *, updated_at=None, source="wss"):
        return self.window.update(
            open_time=minute * MINUTE_MS,
            quote_volume=quote,
            taker_buy_quote_volume=buy,
            closed=True,
            source=source,
            updated_at=updated_at or (minute + 1) * MINUTE_MS,
        )

    def test_same_minute_update_overwrites_cumulative_values(self):
        self.update(15, 100, 60, updated_at=901_000)
        self.update(15, 150, 90, updated_at=902_000)

        row = self.window.snapshot(now_ms=15 * MINUTE_MS + 30_000)

        self.assertEqual(row["cvd15m"], 30)
        self.assertEqual(row["cvd15mRatio"], 0.2)
        self.assertEqual(len(self.window.export_buckets(cutoff_ms=0)), 1)

    def test_older_rest_value_cannot_overwrite_newer_wss_value(self):
        self.update(15, 150, 90, updated_at=902_000)
        accepted = self.update(
            15,
            100,
            60,
            updated_at=901_000,
            source="rest",
        )

        self.assertFalse(accepted)
        self.assertEqual(
            self.window.snapshot(now_ms=15 * MINUTE_MS)["cvd15m"],
            30,
        )

    def test_real_wss_value_overwrites_newer_synthetic_zero(self):
        self.update(
            15,
            0,
            0,
            updated_at=903_000,
            source="synthetic",
        )

        accepted = self.update(
            15,
            150,
            90,
            updated_at=902_000,
            source="wss",
        )

        self.assertTrue(accepted)
        self.assertEqual(
            self.window.snapshot(now_ms=15 * MINUTE_MS)["cvd15m"],
            30,
        )

    def test_lower_priority_source_cannot_overwrite_wss_value(self):
        self.update(15, 150, 90, updated_at=901_000, source="wss")

        accepted = self.update(
            15,
            0,
            0,
            updated_at=999_000,
            source="snapshot",
        )

        self.assertFalse(accepted)
        self.assertEqual(
            self.window.snapshot(now_ms=15 * MINUTE_MS)["cvd15m"],
            30,
        )

    def test_closed_bucket_replaces_open_bucket_from_same_source(self):
        self.window.update(
            open_time=15 * MINUTE_MS,
            quote_volume=150,
            taker_buy_quote_volume=90,
            closed=False,
            source="wss",
            updated_at=902_000,
        )

        accepted = self.window.update(
            open_time=15 * MINUTE_MS,
            quote_volume=200,
            taker_buy_quote_volume=125,
            closed=True,
            source="wss",
            updated_at=901_000,
        )

        self.assertTrue(accepted)
        self.assertEqual(
            self.window.snapshot(now_ms=15 * MINUTE_MS)["cvd15m"],
            50,
        )

    def test_window_uses_current_minute_and_previous_fourteen_only(self):
        for minute in range(1, 17):
            self.update(minute, 100, 60)

        row = self.window.snapshot(now_ms=16 * MINUTE_MS)

        self.assertEqual(row["cvd15m"], 15 * 20)
        self.assertEqual(row["cvdCoverageSeconds"], 900)
        self.assertEqual(row["cvdHealth"], "live")
        self.assertLessEqual(len(self.window.export_buckets(cutoff_ms=0)), BUCKET_COUNT)

    def test_zero_volume_window_is_neutral(self):
        for minute in range(1, 16):
            self.update(minute, 0, 0)

        row = self.window.snapshot(now_ms=15 * MINUTE_MS)

        self.assertEqual(row["cvd15m"], 0)
        self.assertEqual(row["cvd15mRatio"], 0)
        self.assertEqual(row["cvdDirection"], "neutral")

    def test_disconnect_marks_only_health_stale_and_keeps_value(self):
        self.update(15, 100, 75)
        self.window.set_connected(False, "shard disconnected")

        row = self.window.snapshot(now_ms=15 * MINUTE_MS)

        self.assertEqual(row["cvd15m"], 50)
        self.assertEqual(row["cvdHealth"], "stale")
        self.assertEqual(row["cvdStatus"], "buying")
        self.assertEqual(row["cvdReason"], "shard disconnected")

    def test_no_data_is_unavailable(self):
        window = SymbolCvdWindow("ETHUSDT")
        row = window.snapshot(now_ms=15 * MINUTE_MS)

        self.assertIsNone(row["cvd15m"])
        self.assertEqual(row["cvdHealth"], "unavailable")
        self.assertEqual(row["cvdStatus"], "unavailable")


class CvdServiceHealthTests(unittest.TestCase):
    def health(self, **overrides):
        counts = {
            "warming": 0,
            "live": 0,
            "stale": 0,
            "partial": 0,
            "unavailable": 0,
            **overrides,
        }
        return _service_health(counts, connected_shards=2, active_shards=2)

    def test_all_rows_must_be_live_for_service_to_be_live(self):
        self.assertEqual(self.health(live=500), "live")
        self.assertEqual(self.health(live=1, warming=499), "warming")

    def test_unhealthy_rows_make_connected_service_partial(self):
        self.assertEqual(self.health(live=499, stale=1), "partial")

    def test_shard_connectivity_is_reflected_in_service_health(self):
        counts = {"live": 500}
        self.assertEqual(_service_health(counts, 1, 2), "partial")
        self.assertEqual(_service_health(counts, 0, 2), "stale")
        self.assertEqual(_service_health({}, 0, 0), "unavailable")


if __name__ == "__main__":
    unittest.main()
