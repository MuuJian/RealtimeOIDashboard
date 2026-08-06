import unittest

from realtime_oi_dashboard.infrastructure.oi_history_cache import (
    OiHistoryCacheEntry,
    deserialize_history_point,
    export_history_cache,
    restore_history_cache,
)
from realtime_oi_dashboard.domain.oi_history_points import (
    HISTORY_BASELINE_TOLERANCE_MS,
    MAX_SAFE_INTEGER,
)


class HistoryPointSerializationTests(unittest.TestCase):
    def test_deserializes_valid_point(self):
        self.assertEqual(
            deserialize_history_point([1_000, "5.5", "2.0"]),
            (1_000, 5.5, 2.0),
        )

    def test_rejects_invalid_point_fields(self):
        invalid_points = [
            [0, 1, 1],
            [MAX_SAFE_INTEGER + 1, 1, 1],
            [1, -1, 1],
            [1, 1, 0],
            [1, 1],
            "not-a-list",
        ]

        for point in invalid_points:
            with self.subTest(point=point):
                self.assertIsNone(deserialize_history_point(point))


class ExportHistoryCacheTests(unittest.TestCase):
    def test_exports_only_entries_with_remaining_cache_time(self):
        cache = {
            "BTCUSDT": OiHistoryCacheEntry(150.0, (1_000, 5.0, 2.0), None),
            "ETHUSDT": OiHistoryCacheEntry(100.0, (1_000, 3.0, None), None),
        }

        exported = export_history_cache(
            cache,
            monotonic_now=100.0,
            wall_now=1_000.0,
        )

        self.assertEqual(
            exported,
            {
                "BTCUSDT": {
                    "refreshAt": 1_050.0,
                    "past24hPoint": [1_000, 5.0, 2.0],
                    "past7dPoint": None,
                }
            },
        )


class RestoreHistoryCacheTests(unittest.TestCase):
    def test_restores_valid_entry_and_caps_configured_cache_duration(self):
        target_24h = 10_000
        records = {
            "BTCUSDT": {
                "refreshAt": 1_200.0,
                "past24hPoint": [9_000, 5.0, 2.0],
                "past7dPoint": None,
            }
        }

        restored = restore_history_cache(
            records,
            cache_seconds=60,
            target_24h_ms=target_24h,
            target_7d_ms=target_24h,
            wall_now=1_000.0,
            monotonic_now=100.0,
        )

        self.assertEqual(restored["BTCUSDT"].refresh_deadline, 160.0)
        self.assertEqual(restored["BTCUSDT"].past_24h_point, (9_000, 5.0, 2.0))

    def test_source_tolerance_can_shorten_restored_cache(self):
        target = 20_000_000
        remaining_valid_ms = 10_000
        point_timestamp = (
            target - HISTORY_BASELINE_TOLERANCE_MS + remaining_valid_ms
        )
        records = {
            "BTCUSDT": {
                "refreshAt": 2_000.0,
                "past24hPoint": [point_timestamp, 5.0, None],
                "past7dPoint": None,
            }
        }

        restored = restore_history_cache(
            records,
            cache_seconds=300,
            target_24h_ms=target,
            target_7d_ms=target,
            wall_now=1_000.0,
            monotonic_now=50.0,
        )

        self.assertEqual(restored["BTCUSDT"].refresh_deadline, 60.0)

    def test_ignores_expired_malformed_and_invalid_symbol_records(self):
        target = 10_000
        records = {
            "BTC-USDT": {
                "refreshAt": 2_000.0,
                "past24hPoint": [9_000, 5.0, None],
            },
            "ETHUSDT": {
                "refreshAt": 900.0,
                "past24hPoint": [9_000, 5.0, None],
            },
            "SOLUSDT": {
                "refreshAt": 2_000.0,
                "past24hPoint": [0, 5.0, None],
            },
        }

        restored = restore_history_cache(
            records,
            cache_seconds=60,
            target_24h_ms=target,
            target_7d_ms=target,
            wall_now=1_000.0,
            monotonic_now=100.0,
        )

        self.assertEqual(restored, {})


if __name__ == "__main__":
    unittest.main()
