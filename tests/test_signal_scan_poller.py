import threading
import unittest

from realtime_oi_dashboard.signal_scan import (
    EXCHANGE_INFO_URL,
    KLINES_URL,
    SCAN_FAILED_ERROR,
    SIGNAL_SCAN_API_SCHEMA_VERSION,
    SignalScanPoller,
    TICKER_URL,
)


def make_klines(count=120, base=100.0):
    return [[0, 0, base, base, base, 0, 0, 0, 0, 0, 0, 0] for _ in range(count)]


def make_exchange_info(symbols):
    return {
        "symbols": [
            {
                "symbol": s,
                "contractType": "PERPETUAL",
                "underlyingType": "COIN",
                "status": "TRADING",
            }
            for s in symbols
        ]
    }


class FakeHttpClient:
    def __init__(self, tickers, exchange_info, klines_by_symbol, failing_symbols=()):
        self.tickers = tickers
        self.exchange_info = exchange_info
        self.klines_by_symbol = klines_by_symbol
        self.failing_symbols = set(failing_symbols)
        self.closed = False

    def get_json(self, url, params=None, timeout=10, attempts=3):
        if url == TICKER_URL:
            return self.tickers
        if url == EXCHANGE_INFO_URL:
            return self.exchange_info
        if url == KLINES_URL:
            symbol = params["symbol"]
            if symbol in self.failing_symbols:
                raise ValueError(f"{symbol} kline request failed")
            return self.klines_by_symbol[symbol]
        raise AssertionError(f"unexpected URL {url}")

    def close(self):
        self.closed = True


class SignalScanPollerTests(unittest.TestCase):
    def test_successful_scan_populates_state_and_clears_error(self):
        symbols = ["AUSDT", "BUSDT"]
        tickers = [
            {"symbol": s, "quoteVolume": "1000", "priceChangePercent": "1.5"}
            for s in symbols
        ]
        client = FakeHttpClient(
            tickers, make_exchange_info(symbols), {s: make_klines() for s in symbols}
        )
        poller = SignalScanPoller(http_client=client)

        poller.run_scan()
        state = poller.get_state()

        self.assertIsNone(state["error"])
        self.assertIsNotNone(state["saved_at"])
        self.assertEqual(state["schema_version"], SIGNAL_SCAN_API_SCHEMA_VERSION)
        self.assertIn("bulls", state)
        self.assertIn("bears", state)
        self.assertIn("spikes", state)

    def test_one_failing_symbol_does_not_abort_the_scan(self):
        symbols = ["AUSDT", "BUSDT"]
        tickers = [
            {"symbol": s, "quoteVolume": "1000", "priceChangePercent": "1.5"}
            for s in symbols
        ]
        client = FakeHttpClient(
            tickers,
            make_exchange_info(symbols),
            {"AUSDT": make_klines()},
            failing_symbols={"BUSDT"},
        )
        poller = SignalScanPoller(http_client=client)

        poller.run_scan()
        state = poller.get_state()

        self.assertIsNone(state["error"])
        self.assertEqual(
            [event["symbol"] for event in state["recent_errors"]], ["BUSDT"]
        )

    def test_empty_scan_pool_sets_error_and_keeps_empty_lists(self):
        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client)

        poller.run_scan()
        state = poller.get_state()

        self.assertEqual(state["error"], SCAN_FAILED_ERROR)
        self.assertEqual(state["bulls"], [])

    def test_state_is_marked_stale_after_max_age(self):
        symbols = ["AUSDT"]
        tickers = [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}]
        client = FakeHttpClient(tickers, make_exchange_info(symbols), {"AUSDT": make_klines()})
        poller = SignalScanPoller(http_client=client)
        poller.run_scan()

        poller.last_success_wall_clock -= 1000

        state = poller.get_state()

        self.assertEqual(state["bulls"], [])
        self.assertEqual(state["bears"], [])
        self.assertEqual(state["spikes"], [])
        self.assertIsNotNone(state["error"])

    def test_longer_interval_widens_the_stale_window(self):
        symbols = ["AUSDT"]
        tickers = [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}]
        client = FakeHttpClient(tickers, make_exchange_info(symbols), {"AUSDT": make_klines()})
        poller = SignalScanPoller(http_client=client, interval_seconds=120)
        poller.run_scan()
        fresh_state = poller.get_state()

        # 100s old: past the default 90s floor, but within 120 * 1.5 = 180s,
        # so a --signal-scan-interval 120 run should not be treated as stale.
        poller.last_success_wall_clock -= 100

        state = poller.get_state()

        self.assertIsNone(state["error"])
        self.assertEqual(state["saved_at"], fresh_state["saved_at"])
        self.assertEqual(state["bulls"], fresh_state["bulls"])
        self.assertEqual(state["bears"], fresh_state["bears"])
        self.assertEqual(state["spikes"], fresh_state["spikes"])

    def test_stop_before_run_forever_returns_immediately(self):
        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client, interval_seconds=0.01)
        poller.stop()

        thread = threading.Thread(target=poller.run_forever)
        thread.start()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
