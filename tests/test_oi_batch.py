import threading
import time
import unittest
from unittest.mock import patch

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.application.oi.batch import OIBatchRunner
from realtime_oi_dashboard.infrastructure.binance.futures_client import (
    OpenInterestSnapshot,
)


class FakeClient:
    def __init__(self):
        self.history_wall_times = []

    def get_open_interest(self, symbol):
        return OpenInterestSnapshot(value=4.0, timestamp_ms=1_700_000_123_456)

    def get_oi_history_changes(
        self,
        symbol,
        current_oi,
        current_price,
        current_timestamp_ms,
    ):
        self.history_wall_times.append(current_timestamp_ms)
        return {"oiChangePercent24h": 25.0, "oiChangePercent7d": 50.0}


class OIBatchRunnerTests(unittest.TestCase):
    def setUp(self):
        self.stop_event = threading.Event()
        self.errors = []

    def updater(self, workers=1, client=None):
        return OIBatchRunner(
            client or FakeClient(),
            self.stop_event,
            lambda symbol, error: self.errors.append((symbol, str(error))),
            workers=workers,
        )

    def test_sequential_updates_preserve_positions_and_record_errors(self):
        def build_update(symbol, *_):
            if symbol == "ETHUSDT":
                raise ValueError("failed")
            return symbol.lower()

        results = self.updater().run(
            ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            {},
            {},
            {},
            build_update=build_update,
        )

        self.assertEqual(results, ["btcusdt", None, "solusdt"])
        self.assertEqual(self.errors, [("ETHUSDT", "failed")])

    def test_parallel_updates_return_original_batch_order(self):
        delays = {"BTCUSDT": 0.02, "ETHUSDT": 0.01, "SOLUSDT": 0}

        def build_update(symbol, *_):
            time.sleep(delays[symbol])
            return symbol.lower()

        results = self.updater(workers=3).run(
            ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            {},
            {},
            {},
            build_update=build_update,
        )

        self.assertEqual(results, ["btcusdt", "ethusdt", "solusdt"])

    def test_polling_stopped_ends_sequential_batch_without_error(self):
        def build_update(symbol, *_):
            if symbol == "ETHUSDT":
                raise PollingStopped()
            return symbol

        results = self.updater().run(
            ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            {},
            {},
            {},
            build_update=build_update,
        )

        self.assertEqual(results, ["BTCUSDT"])
        self.assertEqual(self.errors, [])

    def test_pre_stopped_runner_does_not_request_symbol_data(self):
        class TrackingClient(FakeClient):
            def __init__(self):
                self.calls = []

            def get_open_interest(self, symbol):
                self.calls.append(symbol)
                return super().get_open_interest(symbol)

        client = TrackingClient()
        self.stop_event.set()

        result = self.updater(client=client).build_symbol_update(
            "BTCUSDT",
            {"BTCUSDT": {"price": 10.0, "volume24h": 1.0}},
            {},
            {},
        )

        self.assertIsNone(result)
        self.assertEqual(client.calls, [])

    def test_build_symbol_update_combines_current_and_cached_market_data(self):
        tickers = {
            "BTCUSDT": {
                "price": 10.0,
                "volume24h": 1_000.0,
                "priceChangePercent": 2.5,
            }
        }
        funding_rates = {
            "BTCUSDT": {
                "fundingRatePercent": 0.01,
                "nextFundingTime": 1_700_000_200_000,
            }
        }
        market_caps = {"BTCUSDT": {"marketCap": 2_000.0}}

        client = FakeClient()
        with (
            patch(
                "realtime_oi_dashboard.application.oi.batch.time.monotonic",
                return_value=123.0,
            ),
        ):
            update = self.updater(client=client).build_symbol_update(
                "BTCUSDT",
                tickers,
                funding_rates,
                market_caps,
            )

        self.assertEqual(update.symbol, "BTCUSDT")
        self.assertEqual(update.measured_at, 123.0)
        self.assertEqual(client.history_wall_times, [1_700_000_123_456])
        self.assertEqual(
            update.row,
            {
                "symbol": "BTCUSDT",
                "price": 10.0,
                "volume24h": 1_000.0,
                "currentOi": 4.0,
                "currentOiValue": 40.0,
                "marketCap": 2_000.0,
                "oiUpdatedAt": 1_700_000_123_456,
                "priceChangePercent": 2.5,
                "fundingRatePercent": 0.01,
                "nextFundingTime": 1_700_000_200_000,
                "oiChangePercent24h": 25.0,
                "oiChangePercent7d": 50.0,
            },
        )

    def test_missing_ticker_is_recorded_as_symbol_failure(self):
        results = self.updater().run(
            ["BTCUSDT"],
            {},
            {},
            {},
        )

        self.assertEqual(results, [None])
        self.assertEqual(self.errors, [("BTCUSDT", "ticker data unavailable")])

if __name__ == "__main__":
    unittest.main()
