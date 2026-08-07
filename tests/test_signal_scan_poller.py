import io
import threading
import time
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from realtime_oi_dashboard.application.signal_scan import (
    EXCHANGE_INFO_URL,
    KLINE_CACHE_MAX_SYMBOLS,
    KLINE_INTERVAL_MILLISECONDS,
    KLINE_LIMIT,
    KLINE_MAX_RESPONSE_ROWS,
    KLINE_REFRESH_LIMIT,
    KLINE_WORKERS,
    KLINES_URL,
    MAX_ERROR_TEXT_LENGTH,
    SCAN_FAILED_ERROR,
    SIGNAL_SCAN_API_SCHEMA_VERSION,
    SIGNAL_SCAN_CLOSE_ATTEMPTS,
    SIGNAL_SCAN_CLOSE_CLIENT_WAIT_SECONDS,
    SIGNAL_SCAN_CLOSE_SCAN_WAIT_SECONDS,
    SIGNAL_SCAN_CLOSE_RETRY_MAX_ATTEMPTS,
    SIGNAL_SCAN_MAX_DURATION_SECONDS,
    SIGNAL_SCAN_MIN_INTERVAL_SECONDS,
    SYMBOL_ERROR_LOG_MAX_ENTRIES,
    SignalScanPoller,
    TICKER_URL,
)
from realtime_oi_dashboard.domain.errors import PollingStopped


def make_klines(count=120, base=100.0):
    return [
        [
            index * KLINE_INTERVAL_MILLISECONDS,
            0,
            base,
            base,
            base,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
        for index in range(count)
    ]


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
        self.ticker_calls = 0
        self.exchange_info_calls = 0
        self.request_attempts = []
        self.kline_requests = []
        self.closed = False

    def get_json(self, url, params=None, timeout=10, attempts=3):
        self.request_attempts.append((url, attempts))
        if url == TICKER_URL:
            self.ticker_calls += 1
            return self.tickers
        if url == EXCHANGE_INFO_URL:
            self.exchange_info_calls += 1
            return self.exchange_info
        if url == KLINES_URL:
            symbol = params["symbol"]
            self.kline_requests.append((symbol, params.get("limit")))
            if symbol in self.failing_symbols:
                raise ValueError(f"{symbol} kline request failed")
            return self.klines_by_symbol[symbol]
        raise AssertionError(f"unexpected URL {url}")

    def close(self):
        self.closed = True


class FailingSnapshotClient(FakeHttpClient):
    def get_json(self, url, params=None, timeout=10, attempts=3):
        if url == TICKER_URL:
            raise ValueError("ticker request failed")
        return super().get_json(url, params, timeout, attempts)


class SignalScanPollerTests(unittest.TestCase):
    def test_rejects_an_injected_client_without_get_json(self):
        with self.assertRaisesRegex(TypeError, "callable get_json"):
            SignalScanPoller(http_client=object())

    def test_rejects_interval_that_overflows_stale_window(self):
        with self.assertRaisesRegex(ValueError, "interval_seconds is too large"):
            SignalScanPoller(
                interval_seconds=1.5e308,
                http_client=FakeHttpClient([], make_exchange_info([]), {}),
            )

    def test_tiny_interval_is_clamped_for_request_safety(self):
        poller = SignalScanPoller(
            interval_seconds=0.1,
            http_client=FakeHttpClient([], make_exchange_info([]), {}),
        )

        self.assertEqual(poller.interval_seconds, 0.1)
        self.assertEqual(
            poller.schedule_interval_seconds,
            SIGNAL_SCAN_MIN_INTERVAL_SECONDS,
        )

    def test_run_forever_uses_the_safe_interval(self):
        client = FakeHttpClient([], make_exchange_info([]), {})

        class OneRoundPoller(SignalScanPoller):
            def run_scan(self):
                self.stop()
                return False

        poller = OneRoundPoller(interval_seconds=0.1, http_client=client)
        waits = []

        with patch(
            "realtime_oi_dashboard.application.signal_scan._wait_for_event",
            side_effect=lambda event, delay: waits.append(delay) or True,
        ):
            poller.run_forever()

        self.assertEqual(waits, [SIGNAL_SCAN_MIN_INTERVAL_SECONDS])

    def test_run_forever_chunks_large_interval_and_still_closes(self):
        scan_started = threading.Event()

        class NoopPoller(SignalScanPoller):
            def run_scan(self):
                scan_started.set()
                return False

        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = NoopPoller(
            interval_seconds=10**10,
            http_client=client,
        )
        poller._owns_http_client = True

        worker = threading.Thread(target=poller.run_forever)
        worker.start()
        self.assertTrue(scan_started.wait(timeout=2))
        poller.stop()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertTrue(client.closed)

    def test_stop_during_kline_request_does_not_publish_success(self):
        started = threading.Event()
        release = threading.Event()
        result = []
        errors = []

        class BlockingKlineClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == KLINES_URL:
                    started.set()
                    release.wait(timeout=2)
                return super().get_json(url, params, timeout, attempts)

        client = BlockingKlineClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)

        def run_scan():
            try:
                result.append(poller.run_scan())
            except Exception as exc:
                errors.append(exc)

        worker = threading.Thread(target=run_scan)
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        poller.stop()
        release.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [])
        self.assertEqual([type(error) for error in errors], [PollingStopped])
        self.assertIsNone(poller.get_state()["saved_at"])

    def test_stop_detaches_blocked_kline_workers_for_injected_client(self):
        started = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        errors = []

        class BlockingKlineClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == KLINES_URL:
                    started.set()
                    release.wait(timeout=5)
                try:
                    return super().get_json(url, params, timeout, attempts)
                finally:
                    if url == KLINES_URL:
                        finished.set()

        client = BlockingKlineClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)
        worker = threading.Thread(
            target=lambda: _capture_error(errors, poller.run_scan),
        )
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        poller.stop()

        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual([type(error) for error in errors], [PollingStopped])
        self.assertTrue(
            all(
                thread.daemon
                for thread in threading.enumerate()
                if thread.name.startswith("signal-kline-AUSDT")
            )
        )

        release.set()
        self.assertTrue(finished.wait(timeout=1))

    def test_run_forever_retries_a_transient_close_failure(self):
        class FlakyCloseClient(FakeHttpClient):
            def __init__(self):
                super().__init__([], make_exchange_info([]), {})
                self.close_calls = 0

            def close(self):
                self.close_calls += 1
                if self.close_calls < SIGNAL_SCAN_CLOSE_ATTEMPTS:
                    raise RuntimeError("close failed")
                self.closed = True

        class OneRoundPoller(SignalScanPoller):
            def run_scan(self):
                self.stop()
                return False

        client = FlakyCloseClient()
        poller = OneRoundPoller(http_client=client)
        poller._owns_http_client = True

        with redirect_stdout(io.StringIO()):
            poller.run_forever()

        self.assertEqual(client.close_calls, SIGNAL_SCAN_CLOSE_ATTEMPTS)
        self.assertTrue(client.closed)
        self.assertTrue(poller._closed)
        self.assertFalse(poller._close_pending)
        self.assertIsNone(poller._close_last_error)

    def test_run_forever_defers_cleanup_after_repeated_close_failures(self):
        class RepeatedCloseFailureClient(FakeHttpClient):
            def __init__(self):
                super().__init__([], make_exchange_info([]), {})
                self.close_calls = 0
                self.closed_event = threading.Event()

            def close(self):
                self.close_calls += 1
                if self.close_calls <= SIGNAL_SCAN_CLOSE_ATTEMPTS:
                    raise RuntimeError("close failed")
                self.closed = True
                self.closed_event.set()

        class OneRoundPoller(SignalScanPoller):
            def run_scan(self):
                self.stop()
                return False

        client = RepeatedCloseFailureClient()
        poller = OneRoundPoller(http_client=client)
        poller._owns_http_client = True

        with patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_RETRY_INITIAL_DELAY_SECONDS",
            0.01,
        ), redirect_stdout(io.StringIO()):
            poller.run_forever()
            self.assertTrue(client.closed_event.wait(timeout=1))
            cleanup_thread = poller._close_retry_thread
            self.assertIsNotNone(cleanup_thread)
            cleanup_thread.join(timeout=1)

        self.assertGreater(client.close_calls, SIGNAL_SCAN_CLOSE_ATTEMPTS)
        self.assertFalse(cleanup_thread.is_alive())
        self.assertTrue(poller._closed)

    def test_deferred_cleanup_stops_after_bounded_retries(self):
        class PermanentCloseFailureClient(FakeHttpClient):
            def __init__(self):
                super().__init__([], make_exchange_info([]), {})
                self.close_calls = 0
                self.allow_close = False

            def close(self):
                self.close_calls += 1
                if not self.allow_close:
                    raise RuntimeError("close permanently failed")
                self.closed = True

        class OneRoundPoller(SignalScanPoller):
            def run_scan(self):
                self.stop()
                return False

        client = PermanentCloseFailureClient()
        poller = OneRoundPoller(http_client=client)
        poller._owns_http_client = True

        with patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_RETRY_INITIAL_DELAY_SECONDS",
            0.001,
        ), redirect_stdout(io.StringIO()):
            poller.run_forever()
            cleanup_thread = poller._close_retry_thread
            self.assertIsNotNone(cleanup_thread)
            cleanup_thread.join(timeout=1)

        self.assertFalse(cleanup_thread.is_alive())
        self.assertEqual(
            client.close_calls,
            SIGNAL_SCAN_CLOSE_ATTEMPTS + SIGNAL_SCAN_CLOSE_RETRY_MAX_ATTEMPTS,
        )
        self.assertTrue(poller._close_pending)
        self.assertTrue(poller._close_retry_exhausted)
        self.assertEqual(poller._close_last_error, "close permanently failed")
        poller._schedule_deferred_close()
        self.assertIs(poller._close_retry_thread, cleanup_thread)

        client.allow_close = True
        poller.close()

        self.assertTrue(client.closed)
        self.assertTrue(poller._closed)
        self.assertFalse(poller._close_pending)
        self.assertFalse(poller._close_retry_exhausted)

    def test_stop_cancels_parallel_kline_round_without_exceeding_worker_cap(self):
        symbols = [f"A{i}USDT" for i in range(6)]
        started = threading.Event()
        release = threading.Event()
        active_lock = threading.Lock()
        active = 0
        max_active = 0
        errors = []

        class BlockingKlineClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                nonlocal active, max_active
                if url != KLINES_URL:
                    return super().get_json(url, params, timeout, attempts)
                with active_lock:
                    active += 1
                    max_active = max(max_active, active)
                    if active == 3:
                        started.set()
                try:
                    release.wait(timeout=2)
                    return super().get_json(url, params, timeout, attempts)
                finally:
                    with active_lock:
                        active -= 1

        client = BlockingKlineClient(
            [
                {
                    "symbol": symbol,
                    "quoteVolume": "1000",
                    "priceChangePercent": "1.5",
                }
                for symbol in symbols
            ],
            make_exchange_info(symbols),
            {symbol: make_klines() for symbol in symbols},
        )
        poller = SignalScanPoller(http_client=client)

        worker = threading.Thread(
            target=lambda: _capture_error(errors, poller.run_scan),
        )
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        poller.stop()
        release.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(max_active, 3)
        self.assertEqual([type(error) for error in errors], [PollingStopped])
        self.assertIsNone(poller.get_state()["saved_at"])

    def test_stop_during_exchange_info_request_does_not_update_cache(self):
        started = threading.Event()
        release = threading.Event()
        errors = []

        class BlockingExchangeInfoClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == EXCHANGE_INFO_URL:
                    started.set()
                    release.wait(timeout=2)
                return super().get_json(url, params, timeout, attempts)

        client = BlockingExchangeInfoClient(
            [],
            make_exchange_info(["AUSDT"]),
            {},
        )
        poller = SignalScanPoller(http_client=client)

        worker = threading.Thread(
            target=lambda: _capture_error(errors, poller.run_scan),
        )
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        poller.stop()
        release.set()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual([type(error) for error in errors], [PollingStopped])
        self.assertIsNone(poller._market_snapshot.peek_exchange_info())

    def test_close_waits_for_external_scan_before_closing_client(self):
        started = threading.Event()
        release = threading.Event()
        close_started = threading.Event()
        close_finished = threading.Event()
        errors = []

        class BlockingTickerClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == TICKER_URL:
                    started.set()
                    release.wait(timeout=2)
                return super().get_json(url, params, timeout, attempts)

        client = BlockingTickerClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        class TrackingPoller(SignalScanPoller):
            def close(self):
                close_started.set()
                super().close()

        poller = TrackingPoller(http_client=client)
        poller._owns_http_client = True

        worker = threading.Thread(
            target=lambda: _capture_error(errors, poller.run_scan),
        )
        worker.start()
        self.assertTrue(started.wait(timeout=2))

        closer = threading.Thread(
            target=lambda: _close_and_mark(poller, close_finished),
        )
        closer.start()
        self.assertTrue(close_started.wait(timeout=2))
        self.assertFalse(close_finished.is_set())
        self.assertFalse(client.closed)

        release.set()
        worker.join(timeout=2)
        closer.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertFalse(closer.is_alive())
        self.assertTrue(close_finished.is_set())
        self.assertTrue(client.closed)
        self.assertEqual([type(error) for error in errors], [PollingStopped])

    def test_owned_close_defers_when_scan_exceeds_shutdown_wait(self):
        started = threading.Event()
        release = threading.Event()
        errors = []

        class BlockingTickerClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == TICKER_URL:
                    started.set()
                    release.wait(timeout=5)
                return super().get_json(url, params, timeout, attempts)

        client = BlockingTickerClient(
            [
                {
                    "symbol": "AUSDT",
                    "quoteVolume": "1000",
                    "priceChangePercent": "1.5",
                }
            ],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)
        poller._owns_http_client = True
        worker = threading.Thread(
            target=lambda: _capture_error(errors, poller.run_scan),
        )
        worker.start()
        self.assertTrue(started.wait(timeout=2))

        with patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_SCAN_WAIT_SECONDS",
            min(0.01, SIGNAL_SCAN_CLOSE_SCAN_WAIT_SECONDS),
        ), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(TimeoutError, "still running"):
                poller.close()

        cleanup_thread = poller._close_retry_thread
        self.assertIsNotNone(cleanup_thread)
        self.assertFalse(client.closed)
        self.assertTrue(poller._close_pending)

        release.set()
        worker.join(timeout=2)
        cleanup_thread.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertFalse(cleanup_thread.is_alive())
        self.assertTrue(client.closed)
        self.assertTrue(poller._closed)
        self.assertEqual([type(error) for error in errors], [PollingStopped])

    def test_blocking_owned_client_close_is_single_flight_and_bounded(self):
        release_close = threading.Event()

        class BlockingCloseClient(FakeHttpClient):
            def __init__(self):
                super().__init__([], make_exchange_info([]), {})
                self.close_calls = 0

            def close(self):
                self.close_calls += 1
                release_close.wait(timeout=5)
                self.closed = True

        client = BlockingCloseClient()
        poller = SignalScanPoller(http_client=client)
        poller._owns_http_client = True

        with patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_CLIENT_WAIT_SECONDS",
            min(0.01, SIGNAL_SCAN_CLOSE_CLIENT_WAIT_SECONDS),
        ), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(TimeoutError, "HTTP client close"):
                poller.close()

            retry_thread = poller._close_retry_thread
            self.assertIsNotNone(retry_thread)
            self.assertEqual(client.close_calls, 1)

            release_close.set()
            retry_thread.join(timeout=2)

        self.assertFalse(retry_thread.is_alive())
        self.assertEqual(client.close_calls, 1)
        self.assertTrue(client.closed)
        self.assertTrue(poller._closed)

    def test_close_does_not_wait_for_injected_client_scan(self):
        started = threading.Event()
        release = threading.Event()
        errors = []

        class BlockingTickerClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == TICKER_URL:
                    started.set()
                    release.wait(timeout=2)
                return super().get_json(url, params, timeout, attempts)

        client = BlockingTickerClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)
        worker = threading.Thread(
            target=lambda: _capture_error(errors, poller.run_scan),
        )
        worker.start()
        self.assertTrue(started.wait(timeout=2))

        closer = threading.Thread(target=poller.close)
        closer.start()
        closer.join(timeout=1)

        self.assertFalse(closer.is_alive())
        self.assertTrue(poller._closed)
        self.assertFalse(client.closed)

        release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual([type(error) for error in errors], [PollingStopped])

    def test_close_rejects_scans_after_shutdown_begins(self):
        client = FakeHttpClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)

        poller.close()

        self.assertFalse(poller.run_scan())
        self.assertEqual(client.ticker_calls, 0)
        poller.close()

    def test_failed_close_schedules_deferred_retry(self):
        class FlakyCloseClient(FakeHttpClient):
            def __init__(self):
                super().__init__([], make_exchange_info([]), {})
                self.close_calls = 0

            def close(self):
                self.close_calls += 1
                if self.close_calls == 1:
                    raise RuntimeError("close failed")
                self.closed = True

        client = FlakyCloseClient()
        poller = SignalScanPoller(http_client=client)
        poller._owns_http_client = True

        with patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_RETRY_INITIAL_DELAY_SECONDS",
            0.05,
        ), self.assertRaisesRegex(RuntimeError, "close failed"):
            poller.close()
        self.assertTrue(poller._closing)
        self.assertFalse(poller.run_scan())
        self.assertEqual(client.ticker_calls, 0)

        retry_thread = poller._close_retry_thread
        self.assertIsNotNone(retry_thread)
        retry_thread.join(timeout=1)

        self.assertEqual(client.close_calls, 2)
        self.assertFalse(retry_thread.is_alive())
        self.assertTrue(client.closed)
        self.assertTrue(poller._closed)
        self.assertFalse(poller._close_pending)
        self.assertIsNone(poller._close_last_error)

    def test_non_exception_close_failure_is_retried_as_cleanup_error(self):
        class InterruptingCloseClient(FakeHttpClient):
            def __init__(self):
                super().__init__([], make_exchange_info([]), {})
                self.close_calls = 0

            def close(self):
                self.close_calls += 1
                if self.close_calls == 1:
                    raise KeyboardInterrupt
                self.closed = True

        client = InterruptingCloseClient()
        poller = SignalScanPoller(http_client=client)
        poller._owns_http_client = True

        with patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_RETRY_INITIAL_DELAY_SECONDS",
            0.001,
        ), redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "KeyboardInterrupt"):
                poller.close()
            retry_thread = poller._close_retry_thread
            self.assertIsNotNone(retry_thread)
            retry_thread.join(timeout=1)

        self.assertFalse(retry_thread.is_alive())
        self.assertEqual(client.close_calls, 2)
        self.assertTrue(client.closed)
        self.assertTrue(poller._closed)

    def test_repeated_deferred_close_failures_are_log_rate_limited(self):
        class AlwaysFailingCloseClient(FakeHttpClient):
            def close(self):
                raise RuntimeError("close failed")

        class OneRoundPoller(SignalScanPoller):
            def run_scan(self):
                self.stop()
                return False

        poller = OneRoundPoller(
            http_client=AlwaysFailingCloseClient([], make_exchange_info([]), {})
        )
        poller._owns_http_client = True
        output = io.StringIO()

        with patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_RETRY_INITIAL_DELAY_SECONDS",
            0.001,
        ), patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_RETRY_MAX_DELAY_SECONDS",
            0.002,
        ), patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_RETRY_MAX_ATTEMPTS",
            100,
        ), patch(
            "realtime_oi_dashboard.application.signal_scan.SIGNAL_SCAN_CLOSE_LOG_COOLDOWN_SECONDS",
            60,
        ), redirect_stdout(output):
            poller.run_forever()
            time.sleep(0.01)

        self.assertEqual(output.getvalue().count("signal scan cleanup failed"), 1)
        self.assertTrue(poller._close_pending)
        self.assertEqual(poller._close_last_error, "close failed")
        poller._close_retry_wakeup.set()
        retry_thread = poller._close_retry_thread
        self.assertIsNotNone(retry_thread)
        retry_thread.join(timeout=1)
        self.assertFalse(retry_thread.is_alive())

    def test_overlapping_scan_is_skipped(self):
        symbols = ["AUSDT"]
        started = threading.Event()
        release = threading.Event()

        class BlockingClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == TICKER_URL:
                    started.set()
                    release.wait(timeout=2)
                return super().get_json(url, params, timeout, attempts)

        client = BlockingClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(symbols),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)
        first_result = []

        worker = threading.Thread(target=lambda: first_result.append(poller.run_scan()))
        worker.start()
        self.assertTrue(started.wait(timeout=2))
        self.assertFalse(poller.run_scan())
        release.set()
        worker.join(timeout=2)

        self.assertEqual(first_result, [True])
        self.assertEqual(client.ticker_calls, 1)

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
        self.assertEqual(state["scan_total"], 2)
        self.assertEqual(state["scan_succeeded"], 2)
        self.assertFalse(state["partial"])
        self.assertTrue(self.client_attempts_are_single_try(client))

    def test_request_json_defaults_to_one_http_attempt(self):
        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client)

        poller.request_json(TICKER_URL)

        self.assertEqual(client.request_attempts, [(TICKER_URL, 1)])

    @staticmethod
    def client_attempts_are_single_try(client):
        return bool(client.request_attempts) and all(
            attempts == 1 for _, attempts in client.request_attempts
        )

    def test_exchange_info_is_cached_between_scan_rounds(self):
        symbols = ["AUSDT"]
        client = FakeHttpClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(symbols),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertTrue(poller.run_scan())
        self.assertTrue(poller.run_scan())

        self.assertEqual(client.ticker_calls, 2)
        self.assertEqual(client.exchange_info_calls, 1)

    def test_klines_use_full_history_once_then_incremental_refresh(self):
        client = FakeHttpClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertTrue(poller.run_scan())
        self.assertTrue(poller.run_scan())

        self.assertEqual(
            [limit for _, limit in client.kline_requests],
            [KLINE_LIMIT, KLINE_REFRESH_LIMIT],
        )
        self.assertEqual(
            len(poller._kline_cache.peek("AUSDT")),
            KLINE_LIMIT,
        )

    def test_thirty_symbol_round_stays_within_incremental_request_budget(self):
        symbols = [f"A{index}USDT" for index in range(30)]

        class LimitRespectingClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == KLINES_URL:
                    symbol = params["symbol"]
                    limit = params.get("limit")
                    self.kline_requests.append((symbol, limit))
                    return [
                        list(candle)
                        for candle in self.klines_by_symbol[symbol][-limit:]
                    ]
                return super().get_json(url, params, timeout, attempts)

        client = LimitRespectingClient(
            [
                {
                    "symbol": symbol,
                    "quoteVolume": str(1000 - index),
                    "priceChangePercent": "1.5",
                }
                for index, symbol in enumerate(symbols)
            ],
            make_exchange_info(symbols),
            {symbol: make_klines() for symbol in symbols},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertTrue(poller.run_scan())
        self.assertTrue(poller.run_scan())

        self.assertEqual(client.ticker_calls, 2)
        self.assertEqual(client.exchange_info_calls, 1)
        self.assertEqual(len(client.kline_requests), 2 * len(symbols))
        self.assertEqual(
            [limit for _, limit in client.kline_requests[: len(symbols)]],
            [KLINE_LIMIT] * len(symbols),
        )
        self.assertEqual(
            [limit for _, limit in client.kline_requests[len(symbols) :]],
            [KLINE_REFRESH_LIMIT] * len(symbols),
        )

    def test_failed_incremental_refresh_recovers_with_full_history(self):
        class FailingIncrementalClient(FakeHttpClient):
            def __init__(self):
                super().__init__(
                    [
                        {
                            "symbol": "AUSDT",
                            "quoteVolume": "1000",
                            "priceChangePercent": "1.5",
                        }
                    ],
                    make_exchange_info(["AUSDT"]),
                    {"AUSDT": make_klines()},
                )
                self.failed_refresh = False

            def get_json(self, url, params=None, timeout=10, attempts=3):
                if (
                    url == KLINES_URL
                    and params.get("limit") == KLINE_REFRESH_LIMIT
                    and not self.failed_refresh
                ):
                    self.failed_refresh = True
                    self.kline_requests.append(("AUSDT", KLINE_REFRESH_LIMIT))
                    raise ValueError("incremental refresh failed")
                return super().get_json(url, params, timeout, attempts)

        client = FailingIncrementalClient()
        poller = SignalScanPoller(http_client=client)

        self.assertTrue(poller.run_scan())
        self.assertTrue(poller.run_scan())

        self.assertEqual(
            [limit for _, limit in client.kline_requests],
            [KLINE_LIMIT, KLINE_REFRESH_LIMIT, KLINE_LIMIT],
        )
        self.assertEqual(
            len(poller._kline_cache.peek("AUSDT")),
            KLINE_LIMIT,
        )

    def test_failed_full_rebuild_discards_cache_before_next_round(self):
        class PersistentlyFailingClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == KLINES_URL and params.get("limit") == KLINE_REFRESH_LIMIT:
                    self.kline_requests.append(("AUSDT", KLINE_REFRESH_LIMIT))
                    history = self.klines_by_symbol["AUSDT"]
                    return [list(history[-1]), list(history[-1])]
                if url == KLINES_URL and params.get("limit") == KLINE_LIMIT:
                    self.kline_requests.append(("AUSDT", KLINE_LIMIT))
                    raise ValueError("full kline request failed")
                return super().get_json(url, params, timeout, attempts)

        client = PersistentlyFailingClient(
            [
                {
                    "symbol": "AUSDT",
                    "quoteVolume": "1000",
                    "priceChangePercent": "1.5",
                }
            ],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)
        self.assertTrue(poller._kline_cache.store("AUSDT", make_klines()))

        self.assertFalse(poller.run_scan())
        self.assertFalse(poller.run_scan())

        self.assertEqual(
            [limit for _, limit in client.kline_requests],
            [KLINE_REFRESH_LIMIT, KLINE_LIMIT, KLINE_LIMIT],
        )
        self.assertNotIn("AUSDT", poller._kline_cache)

    def test_invalid_incremental_open_times_trigger_full_history_fallback(self):
        class UnorderedIncrementalClient(FakeHttpClient):
            def __init__(self):
                history = make_klines()
                super().__init__(
                    [
                        {
                            "symbol": "AUSDT",
                            "quoteVolume": "1000",
                            "priceChangePercent": "1.5",
                        }
                    ],
                    make_exchange_info(["AUSDT"]),
                    {"AUSDT": history},
                )

            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == KLINES_URL and params.get("limit") == KLINE_REFRESH_LIMIT:
                    history = self.klines_by_symbol["AUSDT"]
                    self.kline_requests.append(("AUSDT", KLINE_REFRESH_LIMIT))
                    return [list(history[-1]), list(history[-1])]
                return super().get_json(url, params, timeout, attempts)

        client = UnorderedIncrementalClient()
        poller = SignalScanPoller(http_client=client)

        self.assertTrue(poller.run_scan())
        self.assertTrue(poller.run_scan())

        self.assertEqual(
            [limit for _, limit in client.kline_requests],
            [KLINE_LIMIT, KLINE_REFRESH_LIMIT, KLINE_LIMIT],
        )

    def test_kline_cache_is_bounded_and_does_not_write_after_stop(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )
        for index in range(KLINE_CACHE_MAX_SYMBOLS + 1):
            self.assertTrue(
                poller._kline_cache.store(
                    f"S{index}USDT",
                    make_klines(),
                )
            )

        self.assertEqual(len(poller._kline_cache), KLINE_CACHE_MAX_SYMBOLS)
        self.assertNotIn("S0USDT", poller._kline_cache)

        poller.stop()
        self.assertFalse(
            poller._kline_cache.store("AFTERSTOPUSDT", make_klines())
        )
        self.assertNotIn("AFTERSTOPUSDT", poller._kline_cache)

    def test_incremental_kline_refresh_merges_the_latest_candles(self):
        symbols = ["AUSDT"]
        full_history = [
            [
                index * KLINE_INTERVAL_MILLISECONDS,
                0,
                100,
                100,
                100,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ]
            for index in range(KLINE_LIMIT)
        ]

        class RollingKlineClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == KLINES_URL and params.get("limit") == KLINE_REFRESH_LIMIT:
                    updates = [list(candle) for candle in full_history[-2:]]
                    updates[-1][2:5] = [110, 110, 110]
                    return updates
                return super().get_json(url, params, timeout, attempts)

        client = RollingKlineClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(symbols),
            {"AUSDT": full_history},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertTrue(poller.run_scan())
        self.assertTrue(poller.run_scan())

        cached_history = poller._kline_cache.peek("AUSDT")
        self.assertEqual(len(cached_history), KLINE_LIMIT)
        self.assertEqual(
            cached_history[-1][0],
            (KLINE_LIMIT - 1) * KLINE_INTERVAL_MILLISECONDS,
        )
        self.assertEqual(cached_history[-1][4], 110)

    def test_empty_exchange_info_is_not_cached(self):
        client = FakeHttpClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            {"symbols": []},
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)

        with self.assertRaisesRegex(ValueError, "unexpected exchange-info response"):
            poller.run_scan()

        client.exchange_info = make_exchange_info(["AUSDT"])
        self.assertTrue(poller.run_scan())
        self.assertEqual(client.exchange_info_calls, 2)

    def test_exchange_info_without_non_empty_trading_symbol_is_not_cached(self):
        client = FakeHttpClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            {
                "symbols": [
                    {
                        "symbol": "",
                        "contractType": "PERPETUAL",
                        "underlyingType": "COIN",
                        "status": "TRADING",
                    }
                ]
            },
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)

        with self.assertRaisesRegex(ValueError, "unexpected exchange-info response"):
            poller.run_scan()

        client.exchange_info = make_exchange_info(["AUSDT"])
        self.assertTrue(poller.run_scan())
        self.assertEqual(client.exchange_info_calls, 2)

    def test_invalid_kline_payload_is_reported_per_symbol(self):
        symbols = ["AUSDT", "BUSDT"]
        invalid_klines = make_klines()
        invalid_klines[0][4] = "not-a-price"
        client = FakeHttpClient(
            [
                {"symbol": s, "quoteVolume": "1000", "priceChangePercent": "1.5"}
                for s in symbols
            ],
            make_exchange_info(symbols),
            {"AUSDT": invalid_klines, "BUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertTrue(poller.run_scan())

        state = poller.get_state()
        self.assertIsNone(state["error"])
        self.assertEqual(state["scan_total"], 2)
        self.assertEqual(state["scan_succeeded"], 1)
        self.assertTrue(state["partial"])
        self.assertEqual([event["symbol"] for event in state["recent_errors"]], ["AUSDT"])

    def test_full_history_with_invalid_time_axis_is_rejected(self):
        invalid_history = make_klines()
        invalid_history[40][0] = invalid_history[39][0]
        client = FakeHttpClient(
            [
                {
                    "symbol": "AUSDT",
                    "quoteVolume": "1000",
                    "priceChangePercent": "1.5",
                }
            ],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": invalid_history},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertFalse(poller.run_scan())

        self.assertNotIn("AUSDT", poller._kline_cache)
        self.assertEqual(
            [event["symbol"] for event in poller.get_state()["recent_errors"]],
            ["AUSDT"],
        )

    def test_full_history_with_non_hour_aligned_open_time_is_rejected(self):
        invalid_history = make_klines()
        invalid_history[40][0] += 1
        client = FakeHttpClient(
            [
                {
                    "symbol": "AUSDT",
                    "quoteVolume": "1000",
                    "priceChangePercent": "1.5",
                }
            ],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": invalid_history},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertFalse(poller.run_scan())
        self.assertNotIn("AUSDT", poller._kline_cache)

    def test_full_history_response_is_capped_before_cache_storage(self):
        oversized_history = make_klines(KLINE_MAX_RESPONSE_ROWS + 1)
        client = FakeHttpClient(
            [
                {
                    "symbol": "AUSDT",
                    "quoteVolume": "1000",
                    "priceChangePercent": "1.5",
                }
            ],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": oversized_history},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertFalse(poller.run_scan())

        self.assertNotIn("AUSDT", poller._kline_cache)

    def test_incremental_gap_after_an_overlap_triggers_full_history_fallback(self):
        class GappedIncrementalClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == KLINES_URL and params.get("limit") == KLINE_REFRESH_LIMIT:
                    history = self.klines_by_symbol["AUSDT"]
                    skipped = list(history[-1])
                    skipped[0] += 2 * KLINE_INTERVAL_MILLISECONDS
                    self.kline_requests.append(("AUSDT", KLINE_REFRESH_LIMIT))
                    return [list(history[-1]), skipped]
                return super().get_json(url, params, timeout, attempts)

        client = GappedIncrementalClient(
            [
                {
                    "symbol": "AUSDT",
                    "quoteVolume": "1000",
                    "priceChangePercent": "1.5",
                }
            ],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)

        self.assertTrue(poller.run_scan())
        self.assertTrue(poller.run_scan())

        self.assertEqual(
            [limit for _, limit in client.kline_requests],
            [KLINE_LIMIT, KLINE_REFRESH_LIMIT, KLINE_LIMIT],
        )

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
        self.assertEqual(state["scan_total"], 2)
        self.assertEqual(state["scan_succeeded"], 1)
        self.assertTrue(state["partial"])
        self.assertEqual(
            [event["symbol"] for event in state["recent_errors"]], ["BUSDT"]
        )

    def test_all_failing_symbols_preserve_scan_coverage(self):
        symbols = ["AUSDT", "BUSDT"]
        tickers = [
            {"symbol": s, "quoteVolume": "1000", "priceChangePercent": "1.5"}
            for s in symbols
        ]
        client = FakeHttpClient(
            tickers,
            make_exchange_info(symbols),
            {symbol: make_klines() for symbol in symbols},
            failing_symbols=symbols,
        )
        poller = SignalScanPoller(http_client=client)

        self.assertFalse(poller.run_scan())

        state = poller.get_state()
        self.assertEqual(state["error"], SCAN_FAILED_ERROR)
        self.assertEqual(state["scan_total"], 2)
        self.assertEqual(state["scan_succeeded"], 0)
        self.assertTrue(state["partial"])
        self.assertIsNone(state["saved_at"])

    def test_parallel_classification_preserves_scan_pool_order(self):
        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client)
        poller._classify_ticker = lambda ticker: {"symbol": ticker["symbol"]}

        entries = poller._classify_scan_pool(
            [{"symbol": "AUSDT"}, {"symbol": "BUSDT"}, {"symbol": "CUSDT"}]
        )

        self.assertEqual(
            [entry["symbol"] for entry in entries],
            ["AUSDT", "BUSDT", "CUSDT"],
        )

    def test_parallel_classification_keeps_only_one_worker_window_in_flight(self):
        started = []
        window_ready = threading.Event()
        release = threading.Event()
        errors = []
        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client)

        def classify(ticker):
            started.append(ticker["symbol"])
            if len(started) == KLINE_WORKERS:
                window_ready.set()
            release.wait(timeout=2)
            return {"symbol": ticker["symbol"]}

        poller._classify_ticker = classify
        worker = threading.Thread(
            target=lambda: _capture_result(
                [],
                errors,
                lambda: poller._classify_scan_pool(
                    [
                        {"symbol": f"S{index}USDT"}
                        for index in range(KLINE_WORKERS + 2)
                    ]
                ),
            )
        )
        worker.start()
        self.assertTrue(window_ready.wait(timeout=2))

        self.assertEqual(len(started), KLINE_WORKERS)

        release.set()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    def test_parallel_classification_skips_malformed_tickers(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )
        poller._classify_ticker = lambda ticker: {"symbol": ticker["symbol"]}

        entries = poller._classify_scan_pool(
            [{"symbol": "AUSDT"}, {"symbol": "not-a-symbol"}, {}, {"symbol": "BUSDT"}]
        )

        self.assertEqual(
            [entry["symbol"] for entry in entries],
            ["AUSDT", "BUSDT"],
        )

    def test_parallel_classification_accepts_empty_scan_pool(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )

        self.assertEqual(poller._classify_scan_pool([]), [])

    def test_parallel_classification_rejects_empty_pool_after_stop(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )
        poller.stop()

        with self.assertRaises(PollingStopped):
            poller._classify_scan_pool([])

    def test_parallel_classification_does_not_submit_after_stop(self):
        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client)
        poller.stop()

        with self.assertRaises(PollingStopped):
            poller._classify_scan_pool([{"symbol": "AUSDT"}])

        self.assertEqual(client.request_attempts, [])

    def test_thread_start_failure_is_recorded_without_aborting_window(self):
        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client)
        poller._classify_ticker = lambda ticker: {"symbol": ticker["symbol"]}
        original_start = threading.Thread.start

        def start(thread):
            if thread.name == "signal-kline-BUSDT":
                raise RuntimeError("worker start failed")
            return original_start(thread)

        with patch.object(threading.Thread, "start", start), redirect_stdout(
            io.StringIO()
        ):
            entries = poller._classify_scan_pool(
                [{"symbol": "AUSDT"}, {"symbol": "BUSDT"}, {"symbol": "CUSDT"}]
            )

        self.assertEqual(
            [entry["symbol"] for entry in entries],
            ["AUSDT", "CUSDT"],
        )
        self.assertEqual(
            poller.get_state()["recent_errors"],
            [{"symbol": "BUSDT", "error": "worker start failed"}],
        )

    def test_stop_cancellation_does_not_discard_existing_kline_cache(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )
        history = make_klines()
        self.assertTrue(poller._kline_cache.store("AUSDT", history))
        poller.stop()

        with self.assertRaises(PollingStopped):
            poller._load_full_klines("AUSDT")

        self.assertIn("AUSDT", poller._kline_cache)

    def test_malformed_classification_is_not_counted_as_success(self):
        client = FakeHttpClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(["AUSDT"]),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)
        poller._classify_scan_pool = lambda scan_pool: [{"symbol": "AUSDT"}]

        self.assertFalse(poller.run_scan())
        state = poller.get_state()
        self.assertEqual(state["scan_total"], 1)
        self.assertEqual(state["scan_succeeded"], 0)
        self.assertTrue(state["partial"])
        self.assertEqual(state["error"], SCAN_FAILED_ERROR)

    def test_empty_scan_pool_sets_error_and_keeps_empty_lists(self):
        client = FakeHttpClient([], make_exchange_info(["AUSDT"]), {})
        poller = SignalScanPoller(http_client=client)

        poller.run_scan()
        state = poller.get_state()

        self.assertEqual(state["error"], SCAN_FAILED_ERROR)
        self.assertEqual(state["bulls"], [])

    def test_failed_scan_clears_previous_signals(self):
        symbols = ["AUSDT"]
        client = FakeHttpClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(symbols),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)
        poller.state["bulls"] = [{"symbol": "STALEUSDT"}]
        poller.state["bears"] = [{"symbol": "STALEUSDT"}]
        poller.state["spikes"] = [{"symbol": "STALEUSDT"}]

        client.tickers = []
        client.exchange_info = make_exchange_info(["AUSDT"])
        self.assertFalse(poller.run_scan())

        state = poller.get_state()
        self.assertEqual(state["bulls"], [])
        self.assertEqual(state["bears"], [])
        self.assertEqual(state["spikes"], [])
        self.assertEqual(state["error"], SCAN_FAILED_ERROR)

    def test_snapshot_failure_clears_previous_signals(self):
        client = FailingSnapshotClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client)
        poller.state["bulls"] = [{"symbol": "STALEUSDT"}]
        poller.state["bears"] = [{"symbol": "STALEUSDT"}]
        poller.state["spikes"] = [{"symbol": "STALEUSDT"}]

        with self.assertRaisesRegex(ValueError, "ticker request failed"):
            poller.run_scan()

        state = poller.get_state()
        self.assertEqual(state["bulls"], [])
        self.assertEqual(state["bears"], [])
        self.assertEqual(state["spikes"], [])
        self.assertEqual(state["error"], "ticker request failed")

    def test_malformed_ticker_snapshot_has_explicit_error(self):
        client = FakeHttpClient(
            {"code": -1000, "msg": "invalid ticker payload"},
            make_exchange_info([]),
            {},
        )
        poller = SignalScanPoller(http_client=client)

        with self.assertRaisesRegex(ValueError, "unexpected ticker response"):
            poller.run_scan()

        self.assertEqual(
            poller.get_state()["error"],
            "unexpected ticker response",
        )

    def test_empty_snapshot_exception_has_visible_error_text(self):
        class EmptyErrorClient(FakeHttpClient):
            def get_json(self, url, params=None, timeout=10, attempts=3):
                if url == TICKER_URL:
                    raise ValueError()
                return super().get_json(url, params, timeout, attempts)

        poller = SignalScanPoller(
            http_client=EmptyErrorClient([], make_exchange_info([]), {})
        )

        with self.assertRaises(ValueError):
            poller.run_scan()

        self.assertEqual(poller.get_state()["error"], "ValueError")

    def test_empty_symbol_exception_has_visible_recent_error(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )

        poller.record_symbol_error("AUSDT", ValueError())

        self.assertEqual(
            poller.get_state()["recent_errors"],
            [{"symbol": "AUSDT", "error": "ValueError"}],
        )

    def test_symbol_error_text_is_bounded(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )

        poller.record_symbol_error("AUSDT", ValueError("x" * 1000))

        error_text = poller.get_state()["recent_errors"][0]["error"]
        self.assertEqual(len(error_text), MAX_ERROR_TEXT_LENGTH)
        self.assertTrue(error_text.endswith("..."))

    def test_repeated_symbol_errors_are_rate_limited_in_console(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )
        output = io.StringIO()

        with redirect_stdout(output):
            poller.record_symbol_error("AUSDT", ValueError("first"))
            poller.record_symbol_error("AUSDT", ValueError("second"))

        self.assertEqual(output.getvalue().count("signal scan AUSDT failed"), 1)
        self.assertEqual(
            [event["error"] for event in poller.get_state()["recent_errors"]],
            ["first", "second"],
        )

    def test_symbol_error_log_times_are_pruned_and_bounded(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )
        poller._symbol_error_log_times["OLDUSDT"] = (
            time.monotonic() - 2 * 60 - 1
        )

        with redirect_stdout(io.StringIO()):
            poller.record_symbol_error("NEWUSDT", ValueError("new"))
            for index in range(SYMBOL_ERROR_LOG_MAX_ENTRIES + 50):
                poller.record_symbol_error(
                    f"X{index}USDT",
                    ValueError("churn"),
                )

        self.assertNotIn("OLDUSDT", poller._symbol_error_log_times)
        self.assertLessEqual(
            len(poller._symbol_error_log_times),
            SYMBOL_ERROR_LOG_MAX_ENTRIES,
        )

    def test_malformed_symbol_error_is_ignored(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )

        poller.record_symbol_error([], ValueError("bad symbol"))

        self.assertEqual(poller.get_state()["recent_errors"], [])

    def test_stale_data_does_not_hide_a_scan_failure_reason(self):
        poller = SignalScanPoller(
            http_client=FakeHttpClient([], make_exchange_info([]), {})
        )
        poller.state["saved_at"] = "2026-08-07T12:00:00+08:00"
        poller.last_success_monotonic = time.monotonic() - 1000
        poller._mark_scan_failed("ticker timeout")

        state = poller.get_state()

        self.assertEqual(state["error"], "ticker timeout")

    def test_state_is_marked_stale_after_max_age(self):
        symbols = ["AUSDT"]
        tickers = [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}]
        client = FakeHttpClient(tickers, make_exchange_info(symbols), {"AUSDT": make_klines()})
        poller = SignalScanPoller(http_client=client)
        poller.run_scan()

        poller.last_success_monotonic -= 1000

        state = poller.get_state()

        self.assertEqual(state["bulls"], [])
        self.assertEqual(state["bears"], [])
        self.assertEqual(state["spikes"], [])
        self.assertIsNotNone(state["error"])

    def test_partial_success_state_is_marked_stale_with_error(self):
        symbols = ["AUSDT", "BUSDT"]
        tickers = [
            {"symbol": s, "quoteVolume": "1000", "priceChangePercent": "1.5"}
            for s in symbols
        ]
        client = FakeHttpClient(
            tickers,
            make_exchange_info(symbols),
            {symbol: make_klines() for symbol in symbols},
            failing_symbols={"BUSDT"},
        )
        poller = SignalScanPoller(http_client=client)
        self.assertTrue(poller.run_scan())

        poller.last_success_monotonic -= poller.max_age_seconds + 1
        state = poller.get_state()

        self.assertTrue(state["partial"])
        self.assertEqual(state["scan_total"], 2)
        self.assertEqual(state["scan_succeeded"], 1)
        self.assertIsNotNone(state["saved_at"])
        self.assertIsNotNone(state["error"])

    def test_wall_clock_rollback_does_not_mark_data_stale(self):
        symbols = ["AUSDT"]
        client = FakeHttpClient(
            [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}],
            make_exchange_info(symbols),
            {"AUSDT": make_klines()},
        )
        poller = SignalScanPoller(http_client=client)
        poller.run_scan()
        poller.last_success_wall_clock -= 1000

        state = poller.get_state()

        self.assertIsNone(state["error"])
        self.assertTrue(state["saved_at"])

    def test_longer_interval_widens_the_stale_window(self):
        symbols = ["AUSDT"]
        tickers = [{"symbol": "AUSDT", "quoteVolume": "1000", "priceChangePercent": "1.5"}]
        client = FakeHttpClient(tickers, make_exchange_info(symbols), {"AUSDT": make_klines()})
        poller = SignalScanPoller(http_client=client, interval_seconds=120)
        poller.run_scan()
        fresh_state = poller.get_state()

        # 100s old: past the default 90s floor, but within 120 * 1.5 = 180s,
        # so a --signal-scan-interval 120 run should not be treated as stale.
        poller.last_success_monotonic -= 100

        state = poller.get_state()

        self.assertIsNone(state["error"])
        self.assertEqual(state["saved_at"], fresh_state["saved_at"])
        self.assertEqual(state["bulls"], fresh_state["bulls"])
        self.assertEqual(state["bears"], fresh_state["bears"])
        self.assertEqual(state["spikes"], fresh_state["spikes"])

    def test_stale_window_covers_cooldown_and_worst_scan_duration(self):
        interval_seconds = 60
        poller = SignalScanPoller(
            interval_seconds=interval_seconds,
            http_client=FakeHttpClient([], make_exchange_info([]), {}),
        )

        self.assertGreaterEqual(
            poller.max_age_seconds,
            interval_seconds + SIGNAL_SCAN_MAX_DURATION_SECONDS,
        )

    def test_stop_before_run_forever_returns_immediately(self):
        client = FakeHttpClient([], make_exchange_info([]), {})
        poller = SignalScanPoller(http_client=client, interval_seconds=0.01)
        poller.stop()

        thread = threading.Thread(target=poller.run_forever)
        thread.start()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())


def _capture_error(errors, callback):
    try:
        callback()
    except Exception as error:
        errors.append(error)


def _capture_result(results, errors, callback):
    try:
        results.append(callback())
    except Exception as error:
        errors.append(error)


def _close_and_mark(poller, finished):
    try:
        poller.close()
    finally:
        finished.set()


if __name__ == "__main__":
    unittest.main()
