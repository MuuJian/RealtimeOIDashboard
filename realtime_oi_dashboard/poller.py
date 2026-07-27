"""Realtime Binance Futures open-interest polling and cache state."""

from __future__ import annotations

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from math import isfinite
from pathlib import Path

from realtime_oi_dashboard.binance_client import BinanceFuturesClient
from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.market_data import (
    future_timestamp_ms,
    validate_symbol_refresh,
)
from realtime_oi_dashboard.oi_state import OiStateStore, OiUpdate
from realtime_oi_dashboard.snapshot_store import (
    LoadedSnapshot,
    load_snapshot_file,
    write_snapshot_file,
)


DATA_DIR = Path(__file__).resolve().parent / "data"
ROW_MAX_AGE_SECONDS = 15 * 60
CLOCK_SKEW_SECONDS = 60
RECENT_ERROR_SECONDS = 60
SYMBOL_REFRESH_RETRY_SECONDS = 60
CLOCK_DISCONTINUITY_TOLERANCE_SECONDS = 60
EMPTY_BATCH_ERROR = "本批次没有成功更新任何 OI 数据"
CLOCK_RESET_ERROR = "检测到系统休眠或时钟跳变，正在重新获取 OI 数据"
STALE_ROWS_ERROR = "OI 数据已超过 15 分钟，等待重新获取"
OI_API_SCHEMA_VERSION = 3


class OIPoller:
    def __init__(
        self,
        batch_size=25,
        batch_delay=1.0,
        oi_workers=3,
        refresh_symbols_interval=900,
        oi_history_cache_seconds=300,
        ticker_cache_seconds=10,
        funding_cache_seconds=3600,
        snapshot_save_interval=10,
        snapshot_file=None,
        http_client=None,
    ):
        self.batch_size = _positive_int("batch_size", batch_size)
        self.batch_delay = _non_negative_seconds("batch_delay", batch_delay)
        self.oi_workers = _positive_int("oi_workers", oi_workers)
        self.refresh_symbols_interval = _non_negative_seconds(
            "refresh_symbols_interval",
            refresh_symbols_interval,
        )
        oi_history_cache_seconds = _non_negative_seconds(
            "oi_history_cache_seconds",
            oi_history_cache_seconds,
        )
        ticker_cache_seconds = _non_negative_seconds(
            "ticker_cache_seconds",
            ticker_cache_seconds,
        )
        funding_cache_seconds = _non_negative_seconds(
            "funding_cache_seconds",
            funding_cache_seconds,
        )
        self.snapshot_save_interval = _non_negative_seconds(
            "snapshot_save_interval",
            snapshot_save_interval,
        )
        self.snapshot_file = (
            Path(snapshot_file)
            if snapshot_file
            else DATA_DIR / "latest_oi.json"
        )
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.save_lock = threading.Lock()
        self.symbols = []
        self.symbol_index = 0
        self.last_symbols_refresh = None
        self.symbols_refresh_retry_at = 0.0
        self.pending_symbols_confirmation = None
        self.error_events = deque(maxlen=10)
        self.binance = BinanceFuturesClient(
            self.stop_event,
            self.record_symbol_error,
            oi_history_cache_seconds=oi_history_cache_seconds,
            ticker_cache_seconds=ticker_cache_seconds,
            funding_cache_seconds=funding_cache_seconds,
            http_client=http_client,
        )
        self.last_snapshot_save = None
        loaded_cache = self.load_previous_cache()
        self.binance.restore_oi_history_cache(loaded_cache.oi_history)
        self.known_symbols = loaded_cache.known_symbols
        self.oi_state = OiStateStore(
            max_age_seconds=ROW_MAX_AGE_SECONDS,
        )
        self.state = {
            "saved_at": None,
            "error": None,
        }
        self._last_success_wall_clock = None
        self._last_wall_clock = time.time()
        self._last_monotonic_clock = time.monotonic()

    def load_previous_cache(self):
        try:
            return load_snapshot_file(self.snapshot_file)
        except (OSError, ValueError, RecursionError) as exc:
            print(f"{timestamp()} failed to load previous OI cache: {exc}")
            return LoadedSnapshot()

    def record_symbol_error(self, symbol, exc):
        if self.stop_event.is_set():
            return
        with self.lock:
            if self.stop_event.is_set():
                return
            self.error_events.append(
                {
                    "symbol": symbol,
                    "error": str(exc),
                    "recorded_at": time.monotonic(),
                }
            )
        print(f"{timestamp()} {symbol} update failed: {exc}")

    def recent_errors(self):
        with self.lock:
            cutoff = time.monotonic() - RECENT_ERROR_SECONDS
            while self.error_events and self.error_events[0]["recorded_at"] < cutoff:
                self.error_events.popleft()
            return [
                {"symbol": item["symbol"], "error": item["error"]}
                for item in self.error_events
            ]

    def save_state(self, *, force=False):
        with self.save_lock:
            now = time.monotonic()
            if (
                not force
                and self.snapshot_save_interval > 0
                and self.last_snapshot_save is not None
                and now - self.last_snapshot_save < self.snapshot_save_interval
            ):
                return False

            with self.lock:
                symbols = set(self.symbols or self.known_symbols)
            oi_history = self.binance.export_oi_history_cache()
            write_snapshot_file(
                self.snapshot_file,
                symbols=symbols,
                saved_at=iso_now(),
                oi_history=oi_history,
            )
            self.last_snapshot_save = time.monotonic()
            return True

    def get_active_symbols(self):
        return self.binance.get_active_symbols()

    def get_market_tickers(self):
        with self.lock:
            active_symbols = set(self.symbols)
        return self.binance.get_market_tickers(active_symbols)

    def get_funding_rates(self):
        with self.lock:
            active_symbols = set(self.symbols)
        return self.binance.get_funding_rates(active_symbols)

    def get_open_interest(self, symbol):
        return self.binance.get_open_interest(symbol)

    def get_oi_history_changes(self, symbol, current_oi, current_price):
        return self.binance.get_oi_history_changes(
            symbol,
            current_oi,
            current_price,
        )

    def refresh_symbols_if_needed(self):
        now = time.monotonic()
        with self.lock:
            if now < self.symbols_refresh_retry_at:
                return
            if (
                self.symbols
                and self.last_symbols_refresh is not None
                and now - self.last_symbols_refresh < self.refresh_symbols_interval
            ):
                return
            known_symbols = set(self.symbols) or set(self.known_symbols)

        symbols = None
        try:
            symbols = self.get_active_symbols()
            with self.lock:
                confirmed_large_removal = (
                    tuple(symbols) == self.pending_symbols_confirmation
                )
            validate_symbol_refresh(
                symbols,
                known_symbols,
                confirmed_large_removal=confirmed_large_removal,
            )
        except PollingStopped:
            raise
        except Exception as exc:
            with self.lock:
                if symbols is not None:
                    self.pending_symbols_confirmation = tuple(symbols)
                can_use_existing = bool(self.symbols)
                self.symbols_refresh_retry_at = (
                    time.monotonic() + SYMBOL_REFRESH_RETRY_SECONDS
                )
            if not can_use_existing:
                raise
            self.record_symbol_error("exchangeInfo", exc)
            return

        with self.lock:
            if self.stop_event.is_set():
                return
            symbols_changed = symbols != self.symbols
            has_new_symbols = bool(set(symbols) - set(self.symbols))
            self.symbols = symbols
            self.known_symbols = set(symbols)
            self.last_symbols_refresh = time.monotonic()
            self.symbols_refresh_retry_at = 0.0
            self.pending_symbols_confirmation = None
            if symbols_changed or self.symbol_index >= len(self.symbols):
                self.symbol_index = 0
            self.prune_inactive_symbols(reset_market_caches=has_new_symbols)

    def prune_inactive_symbols(self, *, reset_market_caches=False):
        active = set(self.symbols)
        self.oi_state.retain_symbols(active)
        self.binance.retain_symbols(
            active,
            reset_market_caches=reset_market_caches,
        )

    def prune_stale_data(self, now=None):
        """Drop rows that exceeded the retention window."""
        current_time = time.monotonic() if now is None else now
        return self.oi_state.prune_stale(current_time)

    def _reset_after_clock_discontinuity(
        self,
        *,
        wall_now=None,
        monotonic_now=None,
    ):
        """Discard volatile state when wall and monotonic clocks diverge."""
        current_wall = time.time() if wall_now is None else wall_now
        current_monotonic = (
            time.monotonic() if monotonic_now is None else monotonic_now
        )

        with self.lock:
            wall_elapsed = current_wall - self._last_wall_clock
            monotonic_elapsed = current_monotonic - self._last_monotonic_clock
            self._last_wall_clock = current_wall
            self._last_monotonic_clock = current_monotonic

            if (
                abs(wall_elapsed - monotonic_elapsed)
                <= CLOCK_DISCONTINUITY_TOLERANCE_SECONDS
            ):
                return False

            self.oi_state.clear()
            self.error_events.clear()
            self.symbol_index = 0
            self.last_symbols_refresh = None
            self.symbols_refresh_retry_at = 0.0
            self.pending_symbols_confirmation = None
            self.last_snapshot_save = None
            self.state = {
                "saved_at": None,
                "error": CLOCK_RESET_ERROR,
            }
            self._last_success_wall_clock = None
            self.binance.clear_caches()
            return True

    def next_batch(self):
        if not self.symbols:
            return []

        batch = []
        for _ in range(min(self.batch_size, len(self.symbols))):
            batch.append(self.symbols[self.symbol_index])
            self.symbol_index = (self.symbol_index + 1) % len(self.symbols)
        return batch

    def update_batch(self, executor=None):
        if self.stop_event.is_set():
            return

        self._reset_after_clock_discontinuity()
        self.refresh_symbols_if_needed()
        if self.stop_event.is_set():
            return
        if not self.symbols:
            return

        tickers = self.get_market_tickers()
        if self.stop_event.is_set():
            return
        funding_rates = self.get_funding_rates()
        if self.stop_event.is_set():
            return
        batch_start = self.symbol_index
        batch = self.next_batch()
        if not batch:
            return
        try:
            results = self.update_symbols(
                batch,
                tickers,
                funding_rates,
                executor=executor,
            )
        except BaseException:
            self.symbol_index = batch_start
            raise

        if self.stop_event.is_set():
            return
        if self._reset_after_clock_discontinuity():
            return

        with self.lock:
            if self.stop_event.is_set():
                return
            updated_count = self.oi_state.apply_updates(results)

            self.prune_stale_data()
            if updated_count == 0:
                self.state["error"] = EMPTY_BATCH_ERROR
                return

            saved_at_wall_clock = time.time()
            self._last_success_wall_clock = saved_at_wall_clock
            self.state = {
                "saved_at": iso_now(saved_at_wall_clock),
                "error": None,
            }
        self.save_state()

    def update_symbols(self, batch, tickers, funding_rates, executor=None):
        if self.oi_workers <= 1 or len(batch) <= 1:
            results = []
            for symbol in batch:
                if self.stop_event.is_set():
                    break
                try:
                    results.append(self.build_symbol_update(symbol, tickers, funding_rates))
                except PollingStopped:
                    break
                except Exception as exc:
                    self.record_symbol_error(symbol, exc)
                    results.append(None)
            return results

        if executor is not None:
            return self._update_symbols_parallel(batch, tickers, funding_rates, executor)

        max_workers = min(self.oi_workers, len(batch))
        with ThreadPoolExecutor(max_workers=max_workers) as temporary_executor:
            return self._update_symbols_parallel(
                batch,
                tickers,
                funding_rates,
                temporary_executor,
            )

    def _update_symbols_parallel(self, batch, tickers, funding_rates, executor):
        futures = {}
        try:
            for symbol in batch:
                future = executor.submit(
                    self.build_symbol_update,
                    symbol,
                    tickers,
                    funding_rates,
                )
                futures[future] = symbol
        except BaseException:
            for future in futures:
                future.cancel()
            raise
        results_by_symbol = {symbol: None for symbol in batch}
        for future in as_completed(futures):
            if self.stop_event.is_set():
                for pending in futures:
                    pending.cancel()
                break
            symbol = futures[future]
            try:
                results_by_symbol[symbol] = future.result()
            except PollingStopped:
                for pending in futures:
                    pending.cancel()
                break
            except Exception as exc:
                self.record_symbol_error(symbol, exc)
        return [results_by_symbol[symbol] for symbol in batch]

    def build_symbol_update(self, symbol, tickers, funding_rates):
        if self.stop_event.is_set():
            return None

        ticker = tickers.get(symbol)
        if not ticker:
            raise ValueError("ticker data unavailable")
        price = ticker["price"]
        volume_24h = ticker["volume24h"]

        current_oi = self.get_open_interest(symbol)
        measured_wall_time = time.time()
        measured_at = time.monotonic()
        if self.stop_event.is_set():
            return None
        current_oi_value = current_oi * price
        if not isfinite(current_oi_value):
            raise ValueError("open-interest value is not finite")

        funding = funding_rates.get(symbol, {}) if funding_rates else {}
        funding_rate_percent = funding.get("fundingRatePercent")
        now_ms = int(measured_wall_time * 1000)
        next_funding_time = future_timestamp_ms(funding.get("nextFundingTime"), now_ms)

        oi_history = self.get_oi_history_changes(symbol, current_oi, price)

        row = {
            "symbol": symbol,
            "price": price,
            "volume24h": volume_24h,
            "currentOi": current_oi,
            "currentOiValue": current_oi_value,
            "priceChangePercent": ticker.get("priceChangePercent"),
            "fundingRatePercent": funding_rate_percent,
            "nextFundingTime": next_funding_time,
            **oi_history,
        }
        return OiUpdate(
            symbol=symbol,
            row=row,
            measured_at=measured_at,
        )

    def run_forever(self):
        executor = None
        try:
            if self.stop_event.is_set():
                return
            if self.oi_workers > 1:
                executor = ThreadPoolExecutor(
                    max_workers=self.oi_workers,
                    thread_name_prefix="oi-worker",
                )
            while not self.stop_event.is_set():
                try:
                    self.update_batch(executor=executor)
                except PollingStopped:
                    break
                except Exception as exc:
                    if self.stop_event.is_set():
                        break
                    print(f"{timestamp()} batch update failed: {exc}")
                    with self.lock:
                        self.prune_stale_data()
                        self.state["error"] = str(exc)

                self.stop_event.wait(self.batch_delay)
        finally:
            try:
                if executor is not None:
                    executor.shutdown(wait=True, cancel_futures=True)
            finally:
                self._close_after_polling()

    def stop(self):
        """Signal cancellation, then wait for any active state commit to finish."""
        self.stop_event.set()
        with self.lock:
            # Acquiring the lock is the synchronization barrier.
            pass

    def close(self):
        """Release owned network resources after polling has stopped."""
        self.binance.close()

    def _close_after_polling(self):
        try:
            self.close()
        except Exception as exc:
            print(f"{timestamp()} failed to close OI poller: {exc}")

    def get_state(self):
        with self.lock:
            self.prune_stale_data()
            state = dict(self.state)
            state["schema_version"] = OI_API_SCHEMA_VERSION
            state["total_symbols"] = len(self.symbols)
            rows = self.oi_state.copy_rows()
            if rows and self._wall_clock_rows_are_stale(time.time()):
                rows = []
                state["error"] = STALE_ROWS_ERROR
            state["rows"] = rows
            state["recent_errors"] = self.recent_errors()
            return state

    def _wall_clock_rows_are_stale(self, wall_now):
        if self._last_success_wall_clock is None:
            return True
        age = wall_now - self._last_success_wall_clock
        return (
            not isfinite(age)
            or age < -CLOCK_SKEW_SECONDS
            or age > ROW_MAX_AGE_SECONDS
        )


def _positive_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_seconds(name, value):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite non-negative number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite non-negative number") from exc
    if not isfinite(parsed) or parsed < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return parsed


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def iso_now(wall_time=None):
    current = (
        datetime.now().astimezone()
        if wall_time is None
        else datetime.fromtimestamp(wall_time).astimezone()
    )
    return current.isoformat(timespec="seconds")
