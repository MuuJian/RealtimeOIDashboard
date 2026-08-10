"""Coordinate signal scanning and state publication."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from math import isfinite

from realtime_oi_dashboard.application.oi.health import RecentErrorLog
from realtime_oi_dashboard.application.signal_scan.kline_cache import (
    SignalScanKlineCache,
)
from realtime_oi_dashboard.application.signal_scan.kline_loader import (
    KLINE_CACHE_MAX_SYMBOLS,
    KLINE_INTERVAL,
    KLINE_LIMIT,
    KLINE_REFRESH_LIMIT,
    KLINE_TIMEOUT_SECONDS,
    KLINES_URL,
    SignalScanKlineLoader,
)
from realtime_oi_dashboard.application.signal_scan.market_snapshot import (
    EXCHANGE_INFO_TIMEOUT_SECONDS,
    EXCHANGE_INFO_URL,
    SIGNAL_SCAN_HTTP_ATTEMPTS,
    TICKER_TIMEOUT_SECONDS,
    TICKER_URL,
    SignalScanMarketSnapshotLoader,
)
from realtime_oi_dashboard.application.signal_scan.executor import (
    SignalScanExecutor,
)
from realtime_oi_dashboard.application.signal_scan.state import (
    MAX_ERROR_TEXT_LENGTH,
    SIGNAL_SCAN_API_SCHEMA_VERSION,
    SignalScanStateStore,
    error_text as _error_text,
)
from realtime_oi_dashboard.application.signal_scan.shutdown import (
    SignalScanCloseSettings,
    SignalScanShutdown,
)
from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.signal_scan.rules import (
    SCAN_POOL_SIZE,
    USDT_SYMBOL_PATTERN,
    build_scan_universe,
    filter_signal_entries,
    select_signals,
)
from realtime_oi_dashboard.domain.signal_scan.klines import (
    KLINE_INTERVAL_MILLISECONDS,
    KLINE_MAX_RESPONSE_ROWS,
)
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient


SCAN_MAX_AGE_SECONDS = 90
SCAN_FAILED_ERROR = "本次掃描沒有取得任何幣種資料"
KLINE_WORKERS = 3
# The next scheduled scan is the retry; keep shutdown bounded and avoid a
# retry burst when many symbols fail together.
EVENT_WAIT_CHUNK_SECONDS = 60.0
SYMBOL_ERROR_LOG_COOLDOWN_SECONDS = 60.0
SYMBOL_ERROR_LOG_MAX_ENTRIES = 1024
# A full round includes one all-market ticker request and up to two kline
# requests per symbol. Keep an accidentally tiny interval from creating a
# busy loop.
SIGNAL_SCAN_MIN_INTERVAL_SECONDS = 10.0
SIGNAL_SCAN_CLOSE_ATTEMPTS = 3
SIGNAL_SCAN_CLOSE_SCAN_WAIT_SECONDS = 5.0
SIGNAL_SCAN_CLOSE_CLIENT_WAIT_SECONDS = 5.0
SIGNAL_SCAN_CLOSE_RETRY_INITIAL_DELAY_SECONDS = 0.1
SIGNAL_SCAN_CLOSE_RETRY_MAX_DELAY_SECONDS = 30.0
SIGNAL_SCAN_CLOSE_RETRY_MAX_ATTEMPTS = 5
SIGNAL_SCAN_CLOSE_LOG_COOLDOWN_SECONDS = 60.0
KLINE_COMPLETION_POLL_SECONDS = 0.25
KLINE_REQUESTS_PER_SYMBOL = 2
KLINE_BATCHES = (SCAN_POOL_SIZE + KLINE_WORKERS - 1) // KLINE_WORKERS
SIGNAL_SCAN_MAX_DURATION_SECONDS = (
    TICKER_TIMEOUT_SECONDS
    + EXCHANGE_INFO_TIMEOUT_SECONDS
    + KLINE_BATCHES
    * (
        KLINE_TIMEOUT_SECONDS * KLINE_REQUESTS_PER_SYMBOL
        + KLINE_COMPLETION_POLL_SECONDS
    )
)


class SignalScanPoller:
    """Poll Binance and recompute the bubuaplus.com-equivalent signals.

    An injected HTTP client remains owned by its caller. On cancellation, a
    blocked request from that client may outlive the scan worker in a daemon
    thread; the client must therefore provide its own timeout or cancellation
    behavior so resources can be released promptly.
    """

    def __init__(
        self,
        *,
        interval_seconds=60,
        http_client=None,
        shared_rest_cache=None,
    ):
        self.interval_seconds = _positive_seconds("interval_seconds", interval_seconds)
        if http_client is not None and not callable(
            getattr(http_client, "get_json", None)
        ):
            raise TypeError("http_client must provide a callable get_json")
        self.schedule_interval_seconds = max(
            self.interval_seconds,
            SIGNAL_SCAN_MIN_INTERVAL_SECONDS,
        )
        self.max_age_seconds = max(
            SCAN_MAX_AGE_SECONDS,
            self.schedule_interval_seconds * 1.5,
            self.schedule_interval_seconds + SIGNAL_SCAN_MAX_DURATION_SECONDS,
        )
        if not isfinite(self.max_age_seconds):
            raise ValueError("interval_seconds is too large")
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self._scan_execution_lock = threading.Lock()
        self._owns_http_client = http_client is None
        self.http_client = (
            JsonHttpClient(
                sleep=self._wait_for_retry,
                check_cancelled=self._raise_if_stopped,
            )
            if http_client is None
            else http_client
        )
        self.error_log = RecentErrorLog(self.stop_event)
        self._symbol_error_log_times = {}
        self._state_store = SignalScanStateStore(
            self.lock,
            self.stop_event,
            self.error_log,
            max_age_seconds=self.max_age_seconds,
        )
        self._market_snapshot = SignalScanMarketSnapshotLoader(
            self.request_json,
            self.stop_event,
            shared_rest_cache=shared_rest_cache,
        )
        self._kline_cache = SignalScanKlineCache(
            self.stop_event,
            max_symbols=KLINE_CACHE_MAX_SYMBOLS,
            history_limit=KLINE_LIMIT,
        )
        self._kline_loader = SignalScanKlineLoader(
            self.request_json,
            self._raise_if_stopped,
            self._kline_cache,
        )
        self._scan_executor = SignalScanExecutor(
            self.stop_event,
            self.record_symbol_error,
            self._release_worker_session,
            workers=KLINE_WORKERS,
            poll_seconds=KLINE_COMPLETION_POLL_SECONDS,
            wait_for_workers_on_stop=self._owns_http_client,
        )
        self._shutdown = SignalScanShutdown(
            lock=self.lock,
            scan_execution_lock=self._scan_execution_lock,
            http_client=self.http_client,
            owns_http_client=lambda: self._owns_http_client,
            stop_sources=self._stop_scan_sources,
            settings=_close_settings,
            error_text=_error_text,
            timestamp=_timestamp,
        )

    def _raise_if_stopped(self):
        if self.stop_event.is_set():
            raise PollingStopped

    def _wait_for_retry(self, delay):
        if _wait_for_event(self.stop_event, delay):
            raise PollingStopped

    def request_json(
        self,
        url,
        params=None,
        timeout=10,
        attempts=SIGNAL_SCAN_HTTP_ATTEMPTS,
    ):
        self._raise_if_stopped()
        return self.http_client.get_json(
            url, params=params, timeout=timeout, attempts=attempts
        )

    def run_scan(self) -> bool:
        if not self._scan_execution_lock.acquire(blocking=False):
            return False
        try:
            with self.lock:
                if self._closing:
                    return False
            return self._run_scan()
        except PollingStopped:
            raise
        except Exception as exc:
            self._mark_scan_failed(exc)
            raise
        finally:
            self._scan_execution_lock.release()

    def _run_scan(self) -> bool:
        tickers, exchange_info = self._market_snapshot.load()
        self._raise_if_stopped()
        scan_pool, trend_pool_symbols = build_scan_universe(
            tickers,
            exchange_info,
        )

        if not scan_pool:
            self._mark_scan_failed(SCAN_FAILED_ERROR)
            return False

        entries = filter_signal_entries(self._classify_scan_pool(scan_pool))
        if not entries:
            self._mark_scan_failed(
                SCAN_FAILED_ERROR,
                scan_total=len(scan_pool),
            )
            return False

        self._raise_if_stopped()
        signals = select_signals(entries, trend_pool_symbols)
        self._publish_success(
            signals,
            scan_total=len(scan_pool),
            scan_succeeded=len(entries),
        )
        return True

    def _classify_scan_pool(self, scan_pool: list[dict]) -> list[dict]:
        return self._scan_executor.map(
            scan_pool,
            symbol_for=lambda ticker: (
                _valid_symbol(ticker.get("symbol"))
                if isinstance(ticker, dict)
                else None
            ),
            classify=self._classify_ticker,
        )

    def _release_worker_session(self) -> None:
        release_session = getattr(
            self.http_client,
            "release_current_thread_session",
            None,
        )
        if self._owns_http_client and callable(release_session):
            release_session()

    def _classify_ticker(self, ticker: dict) -> dict | None:
        return self._kline_loader.classify_ticker(ticker)

    def _load_klines(self, symbol: str) -> tuple[list, bool]:
        return self._kline_loader.load(symbol)

    def _load_full_klines(self, symbol: str) -> list:
        return self._kline_loader.load_full(symbol)

    def _request_klines(self, symbol: str, *, limit: int) -> list:
        return self._kline_loader.request(symbol, limit=limit)

    def _publish_success(
        self,
        signals: dict[str, list[dict]],
        *,
        scan_total: int,
        scan_succeeded: int,
    ) -> None:
        self._state_store.publish_success(
            signals,
            scan_total=scan_total,
            scan_succeeded=scan_succeeded,
        )

    def _mark_scan_failed(
        self,
        error: object,
        *,
        scan_total: int = 0,
        scan_succeeded: int = 0,
    ) -> None:
        self._state_store.mark_failed(
            error,
            scan_total=scan_total,
            scan_succeeded=scan_succeeded,
        )

    def record_symbol_error(self, symbol, exc):
        symbol = _valid_symbol(symbol)
        if symbol is None:
            return
        error_text = _error_text(exc)
        error_for_log = RuntimeError(error_text)
        if not self.error_log.record(symbol, error_for_log):
            return

        now = time.monotonic()
        with self.lock:
            self._prune_symbol_error_log_times(now, protected_symbol=symbol)
            previous = self._symbol_error_log_times.get(symbol)
            should_print = (
                previous is None
                or now < previous
                or now - previous >= SYMBOL_ERROR_LOG_COOLDOWN_SECONDS
            )
            if should_print:
                self._symbol_error_log_times[symbol] = now
        if should_print:
            print(f"{_timestamp()} signal scan {symbol} failed: {error_text}")

    def run_forever(self):
        try:
            while not self.stop_event.is_set():
                try:
                    self.run_scan()
                except PollingStopped:
                    break
                except Exception as exc:
                    if self.stop_event.is_set():
                        break
                    print(f"{_timestamp()} signal scan failed: {exc}")
                # Keep a full cooldown after every round so a slow scan cannot
                # turn the next scheduled round into a catch-up request burst.
                _wait_for_event(self.stop_event, self.schedule_interval_seconds)
        finally:
            self._close_after_polling()

    def stop(self):
        with self.lock:
            self._stop_scan_sources()

    def _stop_scan_sources(self):
        self._market_snapshot.stop()
        self._kline_cache.stop()

    def close(self):
        self._shutdown.close()

    def _close_owned_http_client(self):
        self._shutdown.close_owned_http_client()

    def _close_after_polling(self):
        self._shutdown.close_after_polling()

    def _schedule_deferred_close(self):
        self._shutdown.schedule_deferred_close()

    def _retry_close_until_success(self):
        self._shutdown.retry_close_until_success()

    def _log_close_failure(self, error, *, deferred=False, force=False):
        self._shutdown.log_close_failure(
            error,
            deferred=deferred,
            force=force,
        )

    def _prune_symbol_error_log_times(self, now, *, protected_symbol=None):
        cutoff = now - SYMBOL_ERROR_LOG_COOLDOWN_SECONDS
        expired = [
            symbol
            for symbol, recorded_at in self._symbol_error_log_times.items()
            if recorded_at <= cutoff
        ]
        for symbol in expired:
            self._symbol_error_log_times.pop(symbol, None)

        while (
            len(self._symbol_error_log_times) >= SYMBOL_ERROR_LOG_MAX_ENTRIES
            and protected_symbol not in self._symbol_error_log_times
        ):
            oldest_symbol = min(
                self._symbol_error_log_times,
                key=self._symbol_error_log_times.get,
            )
            self._symbol_error_log_times.pop(oldest_symbol, None)

    def get_state(self):
        return self._state_store.snapshot()

    def _is_stale(self):
        return self._state_store.is_stale()

    @property
    def state(self):
        return self._state_store.state

    @state.setter
    def state(self, value):
        self._state_store.state = value

    @property
    def last_success_wall_clock(self):
        return self._state_store.last_success_wall_clock

    @last_success_wall_clock.setter
    def last_success_wall_clock(self, value):
        self._state_store.last_success_wall_clock = value

    @property
    def last_success_monotonic(self):
        return self._state_store.last_success_monotonic

    @last_success_monotonic.setter
    def last_success_monotonic(self, value):
        self._state_store.last_success_monotonic = value

    @property
    def _closing(self):
        return self._shutdown.closing

    @property
    def _closed(self):
        return self._shutdown.closed

    @property
    def _close_pending(self):
        return self._shutdown.close_pending

    @property
    def _close_retry_exhausted(self):
        return self._shutdown.close_retry_exhausted

    @property
    def _close_last_error(self):
        return self._shutdown.close_last_error

    @property
    def _close_retry_thread(self):
        return self._shutdown.close_retry_thread

    @property
    def _close_retry_wakeup(self):
        return self._shutdown.close_retry_wakeup


def _positive_seconds(name, value):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return parsed


def _wait_for_event(event, delay):
    remaining = delay
    while remaining > 0:
        chunk = min(remaining, EVENT_WAIT_CHUNK_SECONDS)
        if event.wait(chunk):
            return True
        remaining -= chunk
    return event.is_set()


def _timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _close_settings():
    return SignalScanCloseSettings(
        attempts=SIGNAL_SCAN_CLOSE_ATTEMPTS,
        scan_wait_seconds=SIGNAL_SCAN_CLOSE_SCAN_WAIT_SECONDS,
        client_wait_seconds=SIGNAL_SCAN_CLOSE_CLIENT_WAIT_SECONDS,
        retry_initial_delay_seconds=SIGNAL_SCAN_CLOSE_RETRY_INITIAL_DELAY_SECONDS,
        retry_max_delay_seconds=SIGNAL_SCAN_CLOSE_RETRY_MAX_DELAY_SECONDS,
        retry_max_attempts=SIGNAL_SCAN_CLOSE_RETRY_MAX_ATTEMPTS,
        log_cooldown_seconds=SIGNAL_SCAN_CLOSE_LOG_COOLDOWN_SECONDS,
    )


def _valid_symbol(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if USDT_SYMBOL_PATTERN.fullmatch(value) else None
