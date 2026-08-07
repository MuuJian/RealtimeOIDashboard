import json
import unittest

from realtime_oi_dashboard.application.cvd import CvdPoller


class FakeHttpClient:
    def __init__(self, tickers, exchange_info):
        self.tickers = tickers
        self.exchange_info = exchange_info

    def get_json(self, url, **_kwargs):
        if url.endswith("ticker/24hr"):
            return self.tickers
        if url.endswith("exchangeInfo"):
            return self.exchange_info
        raise AssertionError(f"unexpected URL: {url}")


class CvdPollerTests(unittest.TestCase):
    def setUp(self):
        self.tickers = [
            {
                "symbol": f"COIN{index}USDT",
                "quoteVolume": str(1000 - index),
            }
            for index in range(35)
        ]
        self.exchange_info = {
            "symbols": [
                {
                    "symbol": ticker["symbol"],
                    "contractType": "PERPETUAL",
                    "underlyingType": "COIN",
                    "status": "TRADING",
                }
                for ticker in self.tickers
            ]
        }

    def test_refresh_universe_tracks_top_30_and_builds_aggtrade_url(self):
        poller = CvdPoller(
            http_client=FakeHttpClient(self.tickers, self.exchange_info),
            now_ms=lambda: 0,
        )

        poller.refresh_universe()

        self.assertEqual(len(poller.get_state()["tracked_symbols"]), 30)
        self.assertIn("coin0usdt@aggTrade", poller.websocket_url)
        self.assertNotIn("coin34usdt@aggTrade", poller.websocket_url)

    def test_combined_aggtrade_event_is_recorded_as_taker_buy(self):
        poller = CvdPoller(
            http_client=FakeHttpClient(self.tickers, self.exchange_info),
            now_ms=lambda: 900_001,
        )
        poller.refresh_universe()

        accepted = poller.handle_message(
            json.dumps(
                {
                    "data": {
                        "s": "COIN0USDT",
                        "E": 10,
                        "p": "100",
                        "q": "2",
                        "m": False,
                    }
                }
            )
        )

        self.assertTrue(accepted)
        row = poller.get_state()["rows"]["COIN0USDT"]
        self.assertEqual(row["cvd15m"], 200)
        self.assertEqual(row["cvdStatus"], "collecting")

    def test_malformed_event_is_ignored_without_losing_the_universe(self):
        poller = CvdPoller(
            http_client=FakeHttpClient(self.tickers, self.exchange_info),
            now_ms=lambda: 0,
        )
        poller.refresh_universe()

        accepted = poller.handle_message('{"data":{"s":"COIN0USDT"}}')

        self.assertFalse(accepted)
        self.assertEqual(len(poller.get_state()["tracked_symbols"]), 30)


if __name__ == "__main__":
    unittest.main()
