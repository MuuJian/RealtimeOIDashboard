import json
import unittest

import websocket

from realtime_oi_dashboard.application.cvd import CvdPoller


class FakeHttpClient:
    def __init__(self, tickers, exchange_info, klines_by_symbol=None):
        self.tickers = tickers
        self.exchange_info = exchange_info
        self.klines_by_symbol = klines_by_symbol or {}
        self.kline_requests = 0

    def get_json(self, url, **_kwargs):
        if url.endswith("ticker/24hr"):
            return self.tickers
        if url.endswith("exchangeInfo"):
            return self.exchange_info
        if url.endswith("klines"):
            self.kline_requests += 1
            symbol = _kwargs["params"]["symbol"]
            response = self.klines_by_symbol[symbol]
            if isinstance(response, Exception):
                raise response
            return response
        raise AssertionError(f"unexpected URL: {url}")


class ManualMonotonicClock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class TimeoutThenLiveWebSocket:
    def __init__(self, clock, stop_event):
        self.clock = clock
        self.stop_event = stop_event
        self.calls = 0

    def recv(self):
        self.calls += 1
        if self.calls == 1:
            self.clock.advance(30)
            raise websocket.WebSocketTimeoutException()
        if self.calls == 2:
            self.clock.advance(29)
            raise websocket.WebSocketTimeoutException()
        if self.calls == 3:
            self.clock.advance(1)
            return json.dumps(
                {
                    "data": {
                        "s": "BTCUSDT",
                        "E": 900_000,
                        "p": "100",
                        "q": "2",
                        "m": False,
                    }
                }
            )
        self.stop_event.set()
        raise websocket.WebSocketTimeoutException()

    def close(self):
        pass


class CvdPollerTests(unittest.TestCase):
    def setUp(self):
        self.tickers = [{"symbol": "BTCUSDT", "quoteVolume": "10000"}] + [
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
        self.assertIn("BTCUSDT", poller.get_state()["tracked_symbols"])
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

    def test_rest_fallback_rebuilds_signed_cvd_from_fifteen_kline_rows(self):
        klines = [
            [
                index * 60_000,
                "0",
                "0",
                "0",
                "0",
                "0",
                (index + 1) * 60_000 - 1,
                "100",
                0,
                "0",
                "60",
                "0",
            ]
            for index in range(15)
        ]
        poller = CvdPoller(
            http_client=FakeHttpClient(
                self.tickers, self.exchange_info, {"BTCUSDT": klines}
            ),
            max_symbols=1,
            now_ms=lambda: 900_000,
        )
        poller.refresh_universe()

        refreshed = poller.refresh_rest_fallback()

        self.assertTrue(refreshed)
        row = poller.get_state()["rows"]["BTCUSDT"]
        self.assertEqual(row["cvd15m"], 300)
        self.assertEqual(row["cvd15mRatio"], 0.2)
        self.assertEqual(row["cvdUpdatedAt"], 899_999)
        self.assertEqual(row["cvdStatus"], "buying")

    def test_invalid_kline_batch_does_not_publish_partial_symbol_cvd(self):
        valid_klines = [
            [
                index * 60_000,
                "0",
                "0",
                "0",
                "0",
                "0",
                (index + 1) * 60_000 - 1,
                "100",
                0,
                "0",
                "60",
                "0",
            ]
            for index in range(15)
        ]
        invalid_klines = [list(kline) for kline in valid_klines]
        invalid_klines[-1][7] = "not-a-number"
        poller = CvdPoller(
            http_client=FakeHttpClient(
                self.tickers,
                self.exchange_info,
                {"BTCUSDT": valid_klines, "COIN0USDT": invalid_klines},
            ),
            max_symbols=2,
            now_ms=lambda: 900_000,
        )
        poller.refresh_universe()

        refreshed = poller.refresh_rest_fallback()

        self.assertTrue(refreshed)
        failed_row = poller.get_state()["rows"]["COIN0USDT"]
        self.assertEqual(failed_row["cvd15m"], 0)
        self.assertEqual(failed_row["cvdStatus"], "collecting")

    def test_failed_rest_fallback_marks_cvd_as_unavailable(self):
        poller = CvdPoller(
            http_client=FakeHttpClient(
                self.tickers,
                self.exchange_info,
                {"BTCUSDT": ConnectionError("REST unavailable")},
            ),
            max_symbols=1,
            now_ms=lambda: 900_000,
        )
        poller.refresh_universe()

        refreshed = poller.refresh_rest_fallback()

        self.assertFalse(refreshed)
        self.assertEqual(poller.get_state()["error"], "CVD unavailable")

    def test_watchdog_uses_rest_once_after_30_seconds_then_returns_to_live_cvd(self):
        klines = [
            [
                index * 60_000,
                "0",
                "0",
                "0",
                "0",
                "0",
                (index + 1) * 60_000 - 1,
                "100",
                0,
                "0",
                "60",
                "0",
            ]
            for index in range(15)
        ]
        clock = ManualMonotonicClock()
        http_client = FakeHttpClient(
            self.tickers, self.exchange_info, {"BTCUSDT": klines}
        )
        poller = CvdPoller(
            http_client=http_client,
            websocket_factory=lambda *_args, **_kwargs: TimeoutThenLiveWebSocket(
                clock, poller.stop_event
            ),
            max_symbols=1,
            interval_seconds=120,
            now_ms=lambda: 900_001,
            monotonic=clock,
        )

        poller.refresh_universe()
        poller._consume_stream()

        row = poller.get_state()["rows"]["BTCUSDT"]
        self.assertEqual(http_client.kline_requests, 1)
        self.assertEqual(row["cvd15m"], 500)
        self.assertEqual(row["cvdUpdatedAt"], 900_000)
        self.assertEqual(poller.get_state()["error"], None)


if __name__ == "__main__":
    unittest.main()
