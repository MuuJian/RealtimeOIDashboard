import threading
import unittest

from realtime_oi_dashboard.application.signal_scan_market_snapshot import (
    EXCHANGE_INFO_TIMEOUT_SECONDS,
    EXCHANGE_INFO_URL,
    SIGNAL_SCAN_HTTP_ATTEMPTS,
    TICKER_TIMEOUT_SECONDS,
    TICKER_URL,
    SignalScanMarketSnapshotLoader,
)
from realtime_oi_dashboard.domain.errors import PollingStopped


def make_exchange_info(symbol="AUSDT"):
    return {
        "symbols": [
            {
                "symbol": symbol,
                "contractType": "PERPETUAL",
                "underlyingType": "COIN",
                "status": "TRADING",
            }
        ]
    }


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


class RecordingRequester:
    def __init__(self):
        self.tickers = []
        self.exchange_info = make_exchange_info()
        self.calls = []

    def __call__(self, url, *, timeout, attempts):
        self.calls.append((url, timeout, attempts))
        if url == TICKER_URL:
            return self.tickers
        if url == EXCHANGE_INFO_URL:
            return self.exchange_info
        raise AssertionError(f"unexpected URL {url}")


class SignalScanMarketSnapshotLoaderTests(unittest.TestCase):
    def create_loader(self, requester=None, *, cache_seconds=900, clock=None):
        requester = RecordingRequester() if requester is None else requester
        stop_event = threading.Event()
        loader = SignalScanMarketSnapshotLoader(
            requester,
            stop_event,
            exchange_info_cache_seconds=cache_seconds,
            monotonic=FakeClock() if clock is None else clock,
        )
        return loader, requester, stop_event

    def test_load_uses_expected_endpoints_and_request_policy(self):
        loader, requester, _ = self.create_loader()

        tickers, exchange_info = loader.load()

        self.assertIs(tickers, requester.tickers)
        self.assertIs(exchange_info, requester.exchange_info)
        self.assertEqual(
            requester.calls,
            [
                (
                    TICKER_URL,
                    TICKER_TIMEOUT_SECONDS,
                    SIGNAL_SCAN_HTTP_ATTEMPTS,
                ),
                (
                    EXCHANGE_INFO_URL,
                    EXCHANGE_INFO_TIMEOUT_SECONDS,
                    SIGNAL_SCAN_HTTP_ATTEMPTS,
                ),
            ],
        )

    def test_exchange_info_is_cached_until_expiry(self):
        clock = FakeClock()
        loader, requester, _ = self.create_loader(
            cache_seconds=10,
            clock=clock,
        )

        first = loader.load_exchange_info()
        clock.value = 9.999
        second = loader.load_exchange_info()
        clock.value = 10.0
        third = loader.load_exchange_info()

        self.assertIs(first, second)
        self.assertIs(third, requester.exchange_info)
        self.assertEqual(
            [url for url, _, _ in requester.calls],
            [EXCHANGE_INFO_URL, EXCHANGE_INFO_URL],
        )

    def test_concurrent_cache_misses_share_one_request(self):
        request_started = threading.Event()
        release_request = threading.Event()
        requester = RecordingRequester()
        original_request = requester.__call__

        def blocking_request(url, *, timeout, attempts):
            if url == EXCHANGE_INFO_URL:
                request_started.set()
                release_request.wait(timeout=2)
            return original_request(url, timeout=timeout, attempts=attempts)

        loader, _, _ = self.create_loader(requester=blocking_request)
        results = []
        errors = []

        def load():
            try:
                results.append(loader.load_exchange_info())
            except BaseException as error:
                errors.append(error)

        workers = [threading.Thread(target=load) for _ in range(2)]
        workers[0].start()
        self.assertTrue(request_started.wait(timeout=2))
        workers[1].start()
        release_request.set()
        for worker in workers:
            worker.join(timeout=2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertIs(results[0], results[1])
        self.assertEqual(len(requester.calls), 1)

    def test_invalid_exchange_info_is_not_cached(self):
        loader, requester, _ = self.create_loader()
        requester.exchange_info = {"symbols": []}

        with self.assertRaisesRegex(ValueError, "unexpected exchange-info"):
            loader.load_exchange_info()

        requester.exchange_info = make_exchange_info()
        self.assertIs(loader.load_exchange_info(), requester.exchange_info)
        self.assertEqual(len(requester.calls), 2)

    def test_invalid_ticker_payload_stops_before_exchange_info(self):
        loader, requester, _ = self.create_loader()
        requester.tickers = {"code": -1}

        with self.assertRaisesRegex(ValueError, "unexpected ticker response"):
            loader.load()

        self.assertEqual(
            [url for url, _, _ in requester.calls],
            [TICKER_URL],
        )

    def test_stop_after_ticker_response_skips_exchange_info_request(self):
        stop_event = threading.Event()
        requester = RecordingRequester()
        original_request = requester.__call__

        def stop_after_ticker(url, *, timeout, attempts):
            response = original_request(
                url,
                timeout=timeout,
                attempts=attempts,
            )
            if url == TICKER_URL:
                stop_event.set()
            return response

        loader = SignalScanMarketSnapshotLoader(
            stop_after_ticker,
            stop_event,
        )

        with self.assertRaises(PollingStopped):
            loader.load()

        self.assertEqual(
            [url for url, _, _ in requester.calls],
            [TICKER_URL],
        )

    def test_stop_during_exchange_request_does_not_cache_response(self):
        request_started = threading.Event()
        release_request = threading.Event()
        requester = RecordingRequester()
        original_request = requester.__call__

        def blocking_request(url, *, timeout, attempts):
            if url == EXCHANGE_INFO_URL:
                request_started.set()
                release_request.wait(timeout=2)
            return original_request(url, timeout=timeout, attempts=attempts)

        loader, _, _ = self.create_loader(requester=blocking_request)
        errors = []

        def load():
            try:
                loader.load_exchange_info()
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=load)
        worker.start()
        self.assertTrue(request_started.wait(timeout=2))
        loader.stop()
        release_request.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual([type(error) for error in errors], [PollingStopped])
        self.assertIsNone(loader.peek_exchange_info())

    def test_stop_waits_for_an_in_progress_cache_write(self):
        exchange_request_returned = threading.Event()
        clock_entered = threading.Event()
        release_clock = threading.Event()
        stop_finished = threading.Event()
        requester = RecordingRequester()
        original_request = requester.__call__

        def request_then_mark(url, *, timeout, attempts):
            response = original_request(url, timeout=timeout, attempts=attempts)
            if url == EXCHANGE_INFO_URL:
                exchange_request_returned.set()
            return response

        def blocking_clock():
            if exchange_request_returned.is_set():
                clock_entered.set()
                release_clock.wait(timeout=2)
            return 1.0

        loader, _, _ = self.create_loader(
            requester=request_then_mark,
            clock=blocking_clock,
        )
        results = []
        load_thread = threading.Thread(
            target=lambda: results.append(loader.load_exchange_info())
        )
        load_thread.start()
        self.assertTrue(clock_entered.wait(timeout=2))

        def stop_loader():
            loader.stop()
            stop_finished.set()

        stop_thread = threading.Thread(target=stop_loader)
        stop_thread.start()
        self.assertFalse(stop_finished.wait(timeout=0.05))

        release_clock.set()
        load_thread.join(timeout=2)
        stop_thread.join(timeout=2)

        self.assertFalse(load_thread.is_alive())
        self.assertFalse(stop_thread.is_alive())
        self.assertEqual(results, [requester.exchange_info])
        self.assertTrue(stop_finished.is_set())
        self.assertIs(loader.peek_exchange_info(), requester.exchange_info)
        with self.assertRaises(PollingStopped):
            loader.load_exchange_info()

    def test_rejects_invalid_cache_duration(self):
        requester = RecordingRequester()
        stop_event = threading.Event()

        for value in (True, False, 0, -1, float("nan"), float("inf"), None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SignalScanMarketSnapshotLoader(
                        requester,
                        stop_event,
                        exchange_info_cache_seconds=value,
                    )

    def test_rejects_invalid_dependencies(self):
        requester = RecordingRequester()
        stop_event = threading.Event()

        with self.assertRaises(TypeError):
            SignalScanMarketSnapshotLoader(None, stop_event)
        with self.assertRaises(TypeError):
            SignalScanMarketSnapshotLoader(requester, object())
        with self.assertRaises(TypeError):
            SignalScanMarketSnapshotLoader(
                requester,
                stop_event,
                monotonic=None,
            )


if __name__ == "__main__":
    unittest.main()
