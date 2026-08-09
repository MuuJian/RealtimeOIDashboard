import inspect
import tempfile
import unittest
from pathlib import Path

from realtime_oi_dashboard.infrastructure.binance.futures_client import BinanceFuturesClient
from realtime_oi_dashboard.infrastructure.coingecko.client import (
    DEFAULT_MARKET_CAP_REFRESH_SECONDS,
    CoinGeckoMarketCapClient,
)
from realtime_oi_dashboard.application.oi.poller import OIPoller


class StubHttpClient:
    def get_json(self, *_args, **_kwargs):
        raise AssertionError("network request was not expected")


class MarketCapRefreshDefaultTests(unittest.TestCase):
    def test_default_is_one_hour(self):
        self.assertEqual(DEFAULT_MARKET_CAP_REFRESH_SECONDS, 3_600)

    def test_poller_uses_the_shared_default(self):
        poller_default = inspect.signature(OIPoller).parameters[
            "market_cap_cache_seconds"
        ].default

        self.assertEqual(poller_default, DEFAULT_MARKET_CAP_REFRESH_SECONDS)

    def test_poller_owns_independent_binance_and_coingecko_clients(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            poller = OIPoller(
                snapshot_file=root / "latest_oi.json",
                market_cap_file=root / "market_caps.json",
                http_client=StubHttpClient(),
            )

            self.assertIsInstance(poller.binance, BinanceFuturesClient)
            self.assertIsInstance(poller.market_caps, CoinGeckoMarketCapClient)
            self.assertIs(poller.binance.http_client, poller.http_client)
            self.assertFalse(hasattr(poller.binance, "market_caps"))
            self.assertEqual(
                poller.market_caps._refresh_seconds,
                DEFAULT_MARKET_CAP_REFRESH_SECONDS,
            )

    def test_binance_client_has_no_coingecko_configuration(self):
        parameters = inspect.signature(BinanceFuturesClient).parameters

        self.assertNotIn("market_cap_cache_seconds", parameters)
        self.assertNotIn("market_cap_file", parameters)


if __name__ == "__main__":
    unittest.main()
