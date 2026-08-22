import inspect
import unittest
from unittest.mock import patch

from realtime_oi_dashboard.application.oi.history import OiHistoryService
from realtime_oi_dashboard.application.oi.poller import OIPoller
from realtime_oi_dashboard.domain.oi.history_points import (
    HISTORY_BASELINE_TOLERANCE_MS,
    HOUR_MS,
)
from realtime_oi_dashboard.infrastructure.binance.futures_client import (
    BinanceFuturesClient,
)


class OiHistoryServiceTests(unittest.TestCase):
    def test_cache_duration_is_not_configurable(self):
        self.assertNotIn(
            "cache_seconds",
            inspect.signature(OiHistoryService).parameters,
        )
        self.assertNotIn(
            "oi_history_cache_seconds",
            inspect.signature(BinanceFuturesClient).parameters,
        )
        self.assertNotIn(
            "oi_history_cache_seconds",
            inspect.signature(OIPoller).parameters,
        )
        self.assertNotIn(
            "ticker_cache_seconds",
            inspect.signature(BinanceFuturesClient).parameters,
        )
        self.assertNotIn(
            "ticker_cache_seconds",
            inspect.signature(OIPoller).parameters,
        )

    def test_successful_history_is_cached_for_one_hour(self):
        now_seconds = 2_000_000_000
        now_ms = int(now_seconds * 1000)
        responses = 0

        def fetch_history(_symbol):
            nonlocal responses
            responses += 1
            return [
                {
                    "timestamp": now_ms - 7 * 24 * HOUR_MS,
                    "sumOpenInterest": "70",
                    "sumOpenInterestValue": "7000",
                },
                {
                    "timestamp": now_ms - 24 * HOUR_MS,
                    "sumOpenInterest": "100",
                    "sumOpenInterestValue": "10000",
                },
            ]

        service = OiHistoryService(fetch_history, lambda *_args: None)
        with patch(
            "realtime_oi_dashboard.application.oi.history.time.monotonic",
            return_value=0,
        ) as monotonic:
            service.get_changes("BTCUSDT", 110, 105, now_ms)
            monotonic.return_value = 3_599
            service.get_changes("BTCUSDT", 110, 105, now_ms)
            monotonic.return_value = 3_600
            service.get_changes("BTCUSDT", 110, 105, now_ms)

        self.assertEqual(responses, 2)

    def test_exchange_time_jump_refreshes_an_out_of_range_cached_baseline(self):
        now_ms = 2_000_000_000_000
        shifted_now_ms = now_ms + HISTORY_BASELINE_TOLERANCE_MS + 1
        responses = iter([
            [
                {
                    "timestamp": now_ms - 7 * 24 * HOUR_MS,
                    "sumOpenInterest": "80",
                    "sumOpenInterestValue": "8000",
                },
                {
                    "timestamp": now_ms - 24 * HOUR_MS,
                    "sumOpenInterest": "100",
                    "sumOpenInterestValue": "10000",
                },
            ],
            [
                {
                    "timestamp": shifted_now_ms - 7 * 24 * HOUR_MS,
                    "sumOpenInterest": "160",
                    "sumOpenInterestValue": "16000",
                },
                {
                    "timestamp": shifted_now_ms - 24 * HOUR_MS,
                    "sumOpenInterest": "125",
                    "sumOpenInterestValue": "12500",
                },
            ],
        ])
        fetches = []

        def fetch_history(symbol):
            fetches.append(symbol)
            return next(responses)

        service = OiHistoryService(fetch_history, lambda *_args: None)
        with patch(
            "realtime_oi_dashboard.application.oi.history.time.monotonic",
            return_value=0,
        ):
            first = service.get_changes("BTCUSDT", 200, 100, now_ms)
            shifted = service.get_changes(
                "BTCUSDT",
                200,
                100,
                shifted_now_ms,
            )

        self.assertEqual(fetches, ["BTCUSDT", "BTCUSDT"])
        self.assertEqual(first["oi24hChangePercent"], 100)
        self.assertEqual(shifted["oi24hChangePercent"], 60)
        self.assertEqual(shifted["oi7dChangePercent"], 25)


if __name__ == "__main__":
    unittest.main()
