"""Background polling and state publication for signal scanning."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from math import isfinite

from realtime_oi_dashboard.application.poller_health import RecentErrorLog
from realtime_oi_dashboard.application.signal_scan_kline_cache import (
    SignalScanKlineCache,
)
from realtime_oi_dashboard.application.signal_scan_market_snapshot import (
    EXCHANGE_INFO_TIMEOUT_SECONDS,
    EXCHANGE_INFO_URL,
    FAPI_BASE_URL,
    SIGNAL_SCAN_HTTP_ATTEMPTS,
    TICKER_TIMEOUT_SECONDS,
    TICKER_URL,
    SignalScanMarketSnapshotLoader,
)
from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.signal_scan import (
    MIN_CANDLES,
    SCAN_POOL_SIZE,
    USDT_SYMBOL_PATTERN,
    build_scan_universe,
    classify_symbol,
    filter_signal_entries,
    select_signals,
)
from realtime_oi_dashboard.domain.signal_scan_klines import (
    KLINE_INTERVAL_MILLISECONDS,
    KLINE_MAX_RESPONSE_ROWS,
    merge_kline_history as _merge_klines,
    normalize_kline_history as _normalize_kline_history,
)
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient


KLINES_URL = f"{FAPI_BASE_URL}/fapi/v1/klines"

SCAN_MAX_AGE_SECONDS = 90
SIGNAL_SCAN_API_SCHEMA_VERSION = 2
SCAN_FAILED_ERROR = "本次掃描沒有取得任何幣種資料"
KLINE_INTERVAL = "1h"
KLINE_LIMIT = 120
KLINE_REFRESH_LIMIT = 2
KLINE_WORKERS = 3
KLINE_CACHE_MAX_SYMBOLS = SCAN_POOL_SIZE * 2
# The next scheduled scan is the retry; keep shutdown bounded and avoid a
# retry burst when many symbols fail together.
KLINE_TIMEOUT_SECONDS = 10
EVENT_WAIT_CHUNK_SECONDS = 60.0
SYMBOL_ERROR_LOG_COOLDOWN_SECONDS = 60.0
SYMBOL_ERROR_LOG_MAX_ENTRIES = 1024
MAX_ERROR_TEXT_LENGTH = 512
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


class _KlineTask:
    def __init__(self, index, symbol):
        self.index = index
        self.symbol = symbol
        self.thread = None
        self.done = threading.Event()
        self.entry = None
        self.error = None


class SignalScanPoller:
    """Poll Binance and recompute the bubuaplus.com-equivalent signals.

    An injected HTTP client remains owned by its caller. On cancellation, a
    blocked request from that client may outlive the scan worker in a daemon
    thread; the client must therefore provide its own timeout or cancellation
    behavior so resources can be released promptly.
    """

    def __init__(self, *, interval_seconds=60, http_client=None):
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
        self._close_lock = threading.Lock()
        self._client_close_state_lock = threading.Lock()
        self._client_close_thread = None
        self._client_close_done = None
        self._client_close_result = None
        self._close_retry_wakeup = threading.Event()
        self._close_retry_thread = None
        self._closing = False
        self._closed = False
        self._close_pending = False
        self._close_retry_exhausted = False
        self._close_last_error = None
        self._close_last_logged_at = None
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
        self.last_success_wall_clock = None
        self.last_success_monotonic = None
        self._market_snapshot = SignalScanMarketSnapshotLoader(
            self.request_json,
            self.stop_event,
        )
        self._kline_cache = SignalScanKlineCache(
            self.stop_event,
            max_symbols=KLINE_CACHE_MAX_SYMBOLS,
            history_limit=KLINE_LIMIT,
        )
        self.state = _empty_state()

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
        self._raise_if_stopped()
        if not scan_pool:
            return []
        indexed_tickers = list(enumerate(scan_pool))
        valid_tickers = []
        for index, ticker in indexed_tickers:
            symbol = _valid_symbol(ticker.get("symbol")) if isinstance(
                ticker, dict
            ) else None
            if symbol is not None:
                valid_tickers.append((index, ticker, symbol))
        if not valid_tickers:
            return []
        self._raise_if_stopped()

        entries_by_index = {}
        worker_count = min(KLINE_WORKERS, len(valid_tickers))
        # Keep Binance concurrency bounded while preserving scan-pool order.
        # Submit only one worker-window at a time so a stop never leaves an
        # entire scan pool queued behind a blocked request.
        tasks = []
        next_ticker_index = 0
        wait_for_workers = True

        def submit_available():
            nonlocal next_ticker_index
            while (
                len(tasks) < worker_count
                and next_ticker_index < len(valid_tickers)
            ):
                self._raise_if_stopped()
                index, ticker, symbol = valid_tickers[next_ticker_index]
                next_ticker_index += 1
                task = _KlineTask(index, symbol)
                task.thread = threading.Thread(
                    target=self._run_kline_task,
                    args=(task, ticker),
                    name=f"signal-kline-{symbol}",
                    daemon=not self._owns_http_client,
                )
                try:
                    task.thread.start()
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit, PollingStopped)):
                        raise
                    self.record_symbol_error(symbol, exc)
                    continue
                tasks.append(task)

        try:
            submit_available()
            while tasks:
                self._raise_if_stopped()
                completed = [task for task in tasks if task.done.is_set()]
                if not completed:
                    if _wait_for_event(
                        self.stop_event,
                        KLINE_COMPLETION_POLL_SECONDS,
                    ):
                        raise PollingStopped
                    continue
                for task in completed:
                    tasks.remove(task)
                    task.thread.join()
                    if task.error is not None:
                        if isinstance(task.error, PollingStopped):
                            raise task.error
                        if not isinstance(task.error, Exception):
                            raise task.error
                        self.record_symbol_error(task.symbol, task.error)
                        continue
                    if task.entry is not None:
                        entries_by_index[task.index] = task.entry
                submit_available()
        except BaseException:
            wait_for_workers = (
                self._owns_http_client or not self.stop_event.is_set()
            )
            raise
        finally:
            # Owned-client workers are joined before the client is closed.
            # Injected-client workers are daemon threads, so a blocked
            # external request cannot keep the process alive after cancel.
            if wait_for_workers:
                for task in tasks:
                    task.thread.join()
        return [
            entries_by_index[index]
            for index, _ in indexed_tickers
            if index in entries_by_index
        ]

    def _run_kline_task(self, task: _KlineTask, ticker: dict) -> None:
        try:
            task.entry = self._classify_ticker(ticker)
        except BaseException as exc:
            task.error = exc
        finally:
            task.done.set()

    def _classify_ticker(self, ticker: dict) -> dict | None:
        symbol = ticker["symbol"]
        klines, used_incremental_cache = self._load_klines(symbol)
        self._raise_if_stopped()
        entry = classify_symbol(
            symbol,
            float(ticker["priceChangePercent"]),
            klines,
        )
        if entry is None and used_incremental_cache:
            # A missed candle or malformed incremental response can make a
            # merge unusable. Rebuild from the full history once before
            # reporting the symbol as failed.
            klines = self._load_full_klines(symbol)
            self._raise_if_stopped()
            entry = classify_symbol(
                symbol,
                float(ticker["priceChangePercent"]),
                klines,
            )
        if entry is None:
            raise ValueError("invalid kline payload")
        if not self._kline_cache.store(symbol, klines):
            self._raise_if_stopped()
            raise ValueError("invalid kline time series")
        return entry

    def _load_klines(self, symbol: str) -> tuple[list, bool]:
        cached = self._kline_cache.get(symbol)
        if cached is None:
            return self._load_full_klines(symbol), False

        try:
            updates = self._request_klines(symbol, limit=KLINE_REFRESH_LIMIT)
        except PollingStopped:
            raise
        except Exception:
            # A failed small refresh must not discard a usable history. Retry
            # once with the full window; the symbol is still marked failed if
            # that recovery request also fails.
            return self._load_full_klines(symbol), False
        merged = _merge_klines(cached, updates, limit=KLINE_LIMIT)
        if merged is None or len(merged) < MIN_CANDLES:
            return self._load_full_klines(symbol), False
        return merged, True

    def _load_full_klines(self, symbol: str) -> list:
        try:
            klines = self._request_klines(symbol, limit=KLINE_LIMIT)
            normalized = _normalize_kline_history(klines, limit=KLINE_LIMIT)
            if normalized is None:
                raise ValueError("invalid kline time series")
            return normalized
        except PollingStopped:
            raise
        except Exception:
            # A failed full rebuild cannot produce a trustworthy signal. Drop
            # the old snapshot so the next round does one full retry instead
            # of repeating an incremental request followed by another full
            # request against the same broken symbol.
            self._kline_cache.discard(symbol)
            raise

    def _request_klines(self, symbol: str, *, limit: int) -> list:
        return self.request_json(
            KLINES_URL,
            params={
                "symbol": symbol,
                "interval": KLINE_INTERVAL,
                "limit": limit,
            },
            timeout=KLINE_TIMEOUT_SECONDS,
            attempts=SIGNAL_SCAN_HTTP_ATTEMPTS,
        )

    def _publish_success(
        self,
        signals: dict[str, list[dict]],
        *,
        scan_total: int,
        scan_succeeded: int,
    ) -> None:
        saved_at = time.time()
        saved_at_monotonic = time.monotonic()
        with self.lock:
            self._raise_if_stopped()
            self.last_success_wall_clock = saved_at
            self.last_success_monotonic = saved_at_monotonic
            self.state = _empty_state()
            self.state.update(
                {
                    "bulls": _copy_rows(signals["bulls"]),
                    "bears": _copy_rows(signals["bears"]),
                    "spikes": _copy_rows(signals["spikes"]),
                    "saved_at": _iso_now(saved_at),
                    "scan_total": scan_total,
                    "scan_succeeded": scan_succeeded,
                    "partial": scan_succeeded < scan_total,
                }
            )

    def _mark_scan_failed(
        self,
        error: object,
        *,
        scan_total: int = 0,
        scan_succeeded: int = 0,
    ) -> None:
        error_text = _error_text(error)
        with self.lock:
            if self.stop_event.is_set():
                return
            saved_at = self.state["saved_at"]
            self.state = _empty_state()
            self.state.update(
                {
                    "saved_at": saved_at,
                    "error": error_text,
                    "scan_total": scan_total,
                    "scan_succeeded": scan_succeeded,
                    "partial": scan_total > scan_succeeded,
                }
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
            self._market_snapshot.stop()
            self._kline_cache.stop()

    def close(self):
        # An owned client must not be closed while a scan can still use it. An
        # injected client belongs to its caller, so shutdown need not wait for
        # that caller's in-flight request.
        deferred_cleanup_needed = False
        close_error = None
        with self._close_lock:
            with self.lock:
                if self._closed:
                    return
                self._closing = True
                self._market_snapshot.stop()
                self._kline_cache.stop()

            if self._owns_http_client:
                acquired = self._scan_execution_lock.acquire(
                    timeout=SIGNAL_SCAN_CLOSE_SCAN_WAIT_SECONDS
                )
                if not acquired:
                    with self.lock:
                        self._close_pending = True
                        self._close_retry_exhausted = False
                        self._close_last_error = "signal scan is still running"
                    deferred_cleanup_needed = True
                else:
                    try:
                        self._close_owned_http_client()
                    except Exception as exc:
                        # Shutdown has started even if the underlying client
                        # needs a retry. Keep the poller closed to new scans
                        # while allowing a later close() call to finish
                        # resource cleanup.
                        with self.lock:
                            self._close_pending = True
                            self._close_retry_exhausted = False
                            self._close_last_error = _error_text(exc)
                        close_error = exc
                        # Any close failure can leave resources open, including
                        # immediate non-timeout failures from the client. Route
                        # all failures through the bounded retry worker so a
                        # direct close() call has the same cleanup guarantee as
                        # run_forever() shutdown.
                        deferred_cleanup_needed = True
                    finally:
                        self._scan_execution_lock.release()

            if not deferred_cleanup_needed and close_error is None:
                with self.lock:
                    self._closed = True
                    self._close_pending = False
                    self._close_retry_exhausted = False
                    self._close_last_error = None
                self._close_retry_wakeup.set()

        if deferred_cleanup_needed:
            self._schedule_deferred_close()
            if close_error is None:
                raise TimeoutError("signal scan is still running")
        if close_error is not None:
            raise close_error

    def _close_owned_http_client(self):
        """Run an owned client's close once and bound the caller's wait."""
        with self._client_close_state_lock:
            done = self._client_close_done
            result = self._client_close_result
            if (
                done is None
                or (
                    done.is_set()
                    and result.get("error") is not None
                    and (
                        self._client_close_thread is None
                        or not self._client_close_thread.is_alive()
                    )
                )
            ):
                done = threading.Event()
                result = {}
                self._client_close_done = done
                self._client_close_result = result
                self._client_close_thread = threading.Thread(
                    target=_run_client_close,
                    args=(self.http_client, done, result),
                    name="signal-scan-http-cleanup",
                    daemon=True,
                )
                self._client_close_thread.start()

        if not done.wait(SIGNAL_SCAN_CLOSE_CLIENT_WAIT_SECONDS):
            raise TimeoutError("signal scan HTTP client close is still running")
        error = result.get("error")
        if error is not None:
            raise error

    def _close_after_polling(self):
        last_error = None
        for _ in range(SIGNAL_SCAN_CLOSE_ATTEMPTS):
            try:
                self.close()
                return
            except Exception as exc:
                last_error = exc
        self._log_close_failure(last_error)
        self._schedule_deferred_close()

    def _schedule_deferred_close(self):
        with self._close_lock:
            with self.lock:
                if (
                    self._closed
                    or not self._close_pending
                    or self._close_retry_exhausted
                ):
                    return
            if (
                self._close_retry_thread is not None
                and self._close_retry_thread.is_alive()
            ):
                return
            self._close_retry_thread = threading.Thread(
                target=self._retry_close_until_success,
                name="signal-scan-cleanup",
                daemon=True,
            )
            self._close_retry_thread.start()

    def _retry_close_until_success(self):
        delay = SIGNAL_SCAN_CLOSE_RETRY_INITIAL_DELAY_SECONDS
        last_error = None
        for _ in range(SIGNAL_SCAN_CLOSE_RETRY_MAX_ATTEMPTS):
            if self._close_retry_wakeup.wait(delay):
                return
            try:
                self.close()
                return
            except Exception as exc:
                last_error = exc
                self._log_close_failure(exc, deferred=True)
                delay = min(
                    delay * 2,
                    SIGNAL_SCAN_CLOSE_RETRY_MAX_DELAY_SECONDS,
                )
        with self.lock:
            self._close_pending = True
            self._close_last_error = _error_text(last_error)
            self._close_retry_exhausted = True
        self._log_close_failure(last_error, deferred=True, force=True)

    def _log_close_failure(self, error, *, deferred=False, force=False):
        now = time.monotonic()
        with self.lock:
            previous = self._close_last_logged_at
            if (
                not force
                and previous is not None
                and now >= previous
                and now - previous < SIGNAL_SCAN_CLOSE_LOG_COOLDOWN_SECONDS
            ):
                return
            self._close_last_logged_at = now
            message = self._close_last_error or _error_text(error)
        prefix = "deferred " if deferred else ""
        print(
            f"{_timestamp()} {prefix}signal scan cleanup failed: {message}"
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
        with self.lock:
            state = _copy_state(self.state)
            state["schema_version"] = SIGNAL_SCAN_API_SCHEMA_VERSION
            state["recent_errors"] = self.error_log.recent()
            if (
                state["saved_at"] is not None
                and state["error"] is None
                and self._is_stale()
            ):
                state["bulls"] = []
                state["bears"] = []
                state["spikes"] = []
                state["error"] = (
                    f"訊號資料已超過 {int(self.max_age_seconds)} 秒，等待重新掃描"
                )
            return state

    def _is_stale(self):
        if self.last_success_monotonic is None:
            return True
        age = time.monotonic() - self.last_success_monotonic
        return (
            not isfinite(age)
            or age < 0
            or age > self.max_age_seconds
        )


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


def _error_text(error: object) -> str:
    message = str(error).strip()
    if message:
        if len(message) <= MAX_ERROR_TEXT_LENGTH:
            return message
        return f"{message[:MAX_ERROR_TEXT_LENGTH - 3]}..."
    if isinstance(error, BaseException):
        return error.__class__.__name__
    return "signal scan failed"


def _run_client_close(client, done, result):
    try:
        client.close()
    except BaseException as error:
        result["error"] = (
            error
            if isinstance(error, Exception)
            else RuntimeError(_error_text(error))
        )
    finally:
        done.set()


def _iso_now(wall_time):
    return datetime.fromtimestamp(wall_time).astimezone().isoformat(
        timespec="seconds"
    )


def _copy_rows(rows: list[dict]) -> list[dict]:
    return [dict(row) for row in rows]


def _empty_state() -> dict:
    return {
        "bulls": [],
        "bears": [],
        "spikes": [],
        "saved_at": None,
        "error": None,
        "scan_total": 0,
        "scan_succeeded": 0,
        "partial": False,
    }


def _copy_state(state: dict) -> dict:
    return {
        "bulls": _copy_rows(state["bulls"]),
        "bears": _copy_rows(state["bears"]),
        "spikes": _copy_rows(state["spikes"]),
        "saved_at": state["saved_at"],
        "error": state["error"],
        "scan_total": state["scan_total"],
        "scan_succeeded": state["scan_succeeded"],
        "partial": state["partial"],
    }


def _valid_symbol(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return value if USDT_SYMBOL_PATTERN.fullmatch(value) else None
