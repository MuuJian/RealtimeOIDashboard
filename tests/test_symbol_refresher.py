import threading
import unittest

from realtime_oi_dashboard.application.oi.symbol_refresher import SymbolRefresher


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


def make_symbols(count):
    return [f"COIN{index}USDT" for index in range(count)]


class SymbolRefresherTests(unittest.TestCase):
    def setUp(self):
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.errors = []
        self.clock = FakeClock()

    def refresher(self, fetch, *, known_symbols=(), refresh_interval=900):
        return SymbolRefresher(
            fetch,
            lambda symbol, error: self.errors.append((symbol, str(error))),
            self.stop_event,
            self.lock,
            refresh_interval=refresh_interval,
            known_symbols=known_symbols,
            monotonic=self.clock,
        )

    def test_success_updates_symbols_and_reports_change_details(self):
        callbacks = []
        symbols = make_symbols(20)
        refresher = self.refresher(lambda **_kwargs: symbols)

        changed = refresher.refresh_if_due(callbacks.append)

        self.assertTrue(changed)
        self.assertEqual(refresher.symbols, symbols)
        self.assertEqual(refresher.known_symbols, set(symbols))
        self.assertTrue(callbacks[0].symbols_changed)
        self.assertTrue(callbacks[0].has_new_symbols)

    def test_refresh_interval_skips_network_request(self):
        requests = []
        symbols = make_symbols(20)
        refresher = self.refresher(
            lambda **_kwargs: requests.append(True) or symbols,
        )
        refresher.refresh_if_due(lambda _refresh: None)

        refreshed = refresher.refresh_if_due(lambda _refresh: None)

        self.assertFalse(refreshed)
        self.assertEqual(requests, [True])

    def test_failed_refresh_keeps_existing_symbols_and_sets_retry(self):
        def fail(**_kwargs):
            raise ValueError("temporary failure")

        refresher = self.refresher(fail)
        refresher.symbols = ["BTCUSDT"]
        refresher.known_symbols = {"BTCUSDT"}

        refreshed = refresher.refresh_if_due(lambda _refresh: None)

        self.assertFalse(refreshed)
        self.assertEqual(refresher.symbols, ["BTCUSDT"])
        self.assertEqual(refresher.retry_at, 160.0)
        self.assertEqual(self.errors, [("exchangeInfo", "temporary failure")])

    def test_large_removal_requires_the_same_result_twice(self):
        existing = make_symbols(30)
        reduced = existing[:-7]
        responses = iter([
            reduced,
            reduced,
        ])
        force_refreshes = []

        def fetch(**kwargs):
            force_refreshes.append(kwargs.get("force_refresh", False))
            return next(responses)

        refresher = self.refresher(fetch, refresh_interval=0)
        refresher.symbols = existing
        refresher.known_symbols = set(existing)

        first = refresher.refresh_if_due(lambda _refresh: None)
        self.clock.value = refresher.retry_at
        second = refresher.refresh_if_due(lambda _refresh: None)

        self.assertFalse(first)
        self.assertTrue(second)
        self.assertEqual(refresher.symbols, reduced)
        self.assertEqual(len(self.errors), 1)
        self.assertEqual(force_refreshes, [False, True])

    def test_initial_failure_is_not_hidden(self):
        refresher = self.refresher(
            lambda **_kwargs: (_ for _ in ()).throw(ValueError("down"))
        )

        with self.assertRaisesRegex(ValueError, "down"):
            refresher.refresh_if_due(lambda _refresh: None)


if __name__ == "__main__":
    unittest.main()
