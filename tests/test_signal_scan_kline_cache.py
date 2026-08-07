import threading
import unittest

from realtime_oi_dashboard.application.signal_scan_kline_cache import (
    SignalScanKlineCache,
)
from realtime_oi_dashboard.domain.signal_scan_klines import (
    KLINE_INTERVAL_MILLISECONDS,
)


def make_klines(count=4, *, close=100):
    return [
        [
            index * KLINE_INTERVAL_MILLISECONDS,
            0,
            close,
            close,
            close,
        ]
        for index in range(count)
    ]


class FakeClock:
    def __init__(self):
        self.value = 0

    def __call__(self):
        self.value += 1
        return self.value


class SignalScanKlineCacheTests(unittest.TestCase):
    def create_cache(self, *, max_symbols=2, history_limit=4, monotonic=None):
        return SignalScanKlineCache(
            threading.Event(),
            max_symbols=max_symbols,
            history_limit=history_limit,
            monotonic=FakeClock() if monotonic is None else monotonic,
        )

    def test_store_and_get_do_not_share_candle_rows(self):
        cache = self.create_cache()
        source = make_klines()

        self.assertTrue(cache.store("AUSDT", source))
        source[-1][4] = 999
        first = cache.get("AUSDT")
        first[-1][4] = 888
        second = cache.get("AUSDT")

        self.assertEqual(second[-1][4], 100)

    def test_get_refreshes_lru_recency(self):
        cache = self.create_cache()
        self.assertTrue(cache.store("AUSDT", make_klines()))
        self.assertTrue(cache.store("BUSDT", make_klines()))

        self.assertIsNotNone(cache.get("AUSDT"))
        self.assertTrue(cache.store("CUSDT", make_klines()))

        self.assertIn("AUSDT", cache)
        self.assertNotIn("BUSDT", cache)
        self.assertIn("CUSDT", cache)

    def test_store_rejects_invalid_history_without_replacing_cache(self):
        cache = self.create_cache()
        self.assertTrue(cache.store("AUSDT", make_klines()))

        self.assertFalse(cache.store("AUSDT", [[0]]))

        self.assertEqual(cache.peek("AUSDT"), make_klines())

    def test_stop_rejects_reads_and_writes_but_preserves_entries(self):
        stop_event = threading.Event()
        cache = SignalScanKlineCache(
            stop_event,
            max_symbols=2,
            history_limit=4,
        )
        self.assertTrue(cache.store("AUSDT", make_klines()))

        cache.stop()

        self.assertIsNone(cache.get("AUSDT"))
        self.assertFalse(cache.store("BUSDT", make_klines()))
        self.assertIn("AUSDT", cache)
        self.assertNotIn("BUSDT", cache)

    def test_discard_is_available_after_stop(self):
        stop_event = threading.Event()
        cache = SignalScanKlineCache(
            stop_event,
            max_symbols=2,
            history_limit=4,
        )
        self.assertTrue(cache.store("AUSDT", make_klines()))
        cache.stop()

        cache.discard("AUSDT")

        self.assertNotIn("AUSDT", cache)

    def test_stop_waits_for_an_in_progress_store_before_returning(self):
        clock_entered = threading.Event()
        release_clock = threading.Event()
        stop_finished = threading.Event()

        def blocking_clock():
            clock_entered.set()
            release_clock.wait(timeout=2)
            return 1

        cache = self.create_cache(monotonic=blocking_clock)
        store_result = []
        store_thread = threading.Thread(
            target=lambda: store_result.append(
                cache.store("AUSDT", make_klines())
            )
        )
        store_thread.start()
        self.assertTrue(clock_entered.wait(timeout=2))

        def stop_cache():
            cache.stop()
            stop_finished.set()

        stop_thread = threading.Thread(target=stop_cache)
        stop_thread.start()
        self.assertFalse(stop_finished.wait(timeout=0.05))

        release_clock.set()
        store_thread.join(timeout=2)
        stop_thread.join(timeout=2)

        self.assertFalse(store_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(store_result, [True])
        self.assertTrue(stop_finished.is_set())
        self.assertIn("AUSDT", cache)
        self.assertFalse(cache.store("BUSDT", make_klines()))

    def test_invalid_symbol_keys_are_ignored(self):
        cache = self.create_cache()

        for symbol in (None, "", [], {}):
            with self.subTest(symbol=symbol):
                self.assertFalse(cache.store(symbol, make_klines()))
                self.assertIsNone(cache.get(symbol))
                self.assertIsNone(cache.peek(symbol))
                self.assertNotIn(symbol, cache)
                cache.discard(symbol)

        self.assertEqual(len(cache), 0)

    def test_concurrent_churn_remains_bounded_and_error_free(self):
        cache = self.create_cache(max_symbols=4)
        start = threading.Barrier(8)
        errors = []

        def churn(worker_index):
            try:
                start.wait(timeout=2)
                for iteration in range(200):
                    symbol = f"S{worker_index}-{iteration % 5}USDT"
                    cache.store(symbol, make_klines(close=iteration + 1))
                    snapshot = cache.get(symbol)
                    if snapshot is not None:
                        snapshot[-1][4] = -1
                    if iteration % 11 == 0:
                        cache.discard(symbol)
            except BaseException as error:
                errors.append(error)

        workers = [
            threading.Thread(target=churn, args=(index,))
            for index in range(8)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=5)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertLessEqual(len(cache), 4)

    def test_rejects_invalid_configuration(self):
        stop_event = threading.Event()
        for value in (True, False, 0, -1, 1.5, "2", None):
            with self.subTest(max_symbols=value):
                with self.assertRaises(ValueError):
                    SignalScanKlineCache(
                        stop_event,
                        max_symbols=value,
                        history_limit=4,
                    )
            with self.subTest(history_limit=value):
                with self.assertRaises(ValueError):
                    SignalScanKlineCache(
                        stop_event,
                        max_symbols=2,
                        history_limit=value,
                    )


if __name__ == "__main__":
    unittest.main()
