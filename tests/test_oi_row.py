import threading
import unittest
from unittest.mock import patch

from realtime_oi_dashboard.oi_row import OIRowBuilder


class StubClient:
    def get_open_interest(self, symbol):
        self.requested_symbol = symbol
        return 12.0

    def get_oi_history_changes(self, symbol, current_oi, current_price):
        self.history_request = (symbol, current_oi, current_price)
        return {
            "oiChange24h": 1.25,
            "oiChange7d": -2.5,
        }


class OIRowBuilderTests(unittest.TestCase):
    def test_build_preserves_dashboard_row_contract(self):
        client = StubClient()
        builder = OIRowBuilder(client, threading.Event())
        tickers = {
            "BTCUSDT": {
                "price": 100.0,
                "volume24h": 5_000.0,
                "priceChangePercent": 3.5,
            },
        }
        funding = {
            "BTCUSDT": {
                "fundingRatePercent": 0.01,
                "nextFundingTime": 1_800_000,
            },
        }

        with (
            patch("realtime_oi_dashboard.oi_row.time.time", return_value=1_000.0),
            patch(
                "realtime_oi_dashboard.oi_row.time.monotonic",
                return_value=200.0,
            ),
        ):
            update = builder.build(
                "BTCUSDT",
                tickers,
                funding,
                {"BTCUSDT": {"marketCap": 20_000.0}},
            )

        self.assertEqual(update.symbol, "BTCUSDT")
        self.assertEqual(update.measured_at, 200.0)
        self.assertEqual(
            update.row,
            {
                "symbol": "BTCUSDT",
                "price": 100.0,
                "volume24h": 5_000.0,
                "currentOi": 12.0,
                "currentOiValue": 1_200.0,
                "marketCap": 20_000.0,
                "oiUpdatedAt": 1_000_000,
                "priceChangePercent": 3.5,
                "fundingRatePercent": 0.01,
                "nextFundingTime": 1_800_000,
                "oiChange24h": 1.25,
                "oiChange7d": -2.5,
            },
        )
        self.assertEqual(client.requested_symbol, "BTCUSDT")
        self.assertEqual(client.history_request, ("BTCUSDT", 12.0, 100.0))

    def test_stopped_builder_does_not_request_network_data(self):
        stop_event = threading.Event()
        stop_event.set()
        client = StubClient()

        result = OIRowBuilder(client, stop_event).build(
            "BTCUSDT",
            {},
            {},
        )

        self.assertIsNone(result)
        self.assertFalse(hasattr(client, "requested_symbol"))


if __name__ == "__main__":
    unittest.main()
