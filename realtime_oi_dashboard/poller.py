"""Realtime Binance Futures open-interest polling and cache state."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from math import isfinite
from pathlib import Path

from realtime_oi_dashboard.batch_selector import RoundRobinBatchSelector
from realtime_oi_dashboard.binance_client import BinanceFuturesClient
from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.http import JsonHttpClient
from realtime_oi_dashboard.market_cap_client import (
    DEFAULT_MARKET_CAP_REFRESH_SECONDS,
    CoinGeckoMarketCapClient,
)
from realtime_oi_dashboard.market_data import validate_symbol_refresh
from realtime_oi_dashboard.market_snapshot import MarketSnapshotProvider
from realtime_oi_dashboard.oi_batch import OiBatchUpdater
from realtime_oi_dashboard.poller_health import PollerClock, RecentErrorLog
from realtime_oi_dashboard.oi_state import OiStateStore
from realtime_oi_dashboard.snapshot_store import (
    LoadedSnapshot,
    load_snapshot_file,
    write_snapshot_file,
)


DATA_DIR = Path(__file__).resolve().parent / "data"
ROW_MAX_AGE_SECONDS = 15 * 60
CLOCK_SKEW_SECONDS = 60
SYMBOL_REFRESH_RETRY_SECONDS = 60
EMPTY_BATCH_ERROR = "本批次没有成功更新任何 OI 数据"
CLOCK_RESET_ERROR = "检测到系统休眠或时钟跳变，正在重新获取 OI 数据"
STALE_ROWS_ERROR = "OI 数据已超过 15 分钟，等待重新获取"
OI_API_SCHEMA_VERSION = 7


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
        market_cap_cache_seconds=DEFAULT_MARKET_CAP_REFRESH_SECONDS,
        snapshot_save_interval=10,
        snapshot_file=None,
        market_cap_file=None,
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
        market_cap_cache_seconds = _non_negative_seconds(
            "market_cap_cache_seconds",
            market_cap_cache_seconds,
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
        self.market_cap_file = (
            Path(market_cap_file)
            if market_cap_file
            else DATA_DIR / "market_caps.json"
        )
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.save_lock = threading.Lock()
        self.symbols = []
        self.batch_selector = RoundRobinBatchSelector(self.batch_size)
        self.last_symbols_refresh = None
        self.symbols_refresh_retry_at = 0.0
        self.pending_symbols_confirmation = None
        self.error_log = RecentErrorLog(self.stop_event)
        self._owns_http_client = http_client is None
        self.http_client = (
            JsonHttpClient(
                sleep=self._wait_for_retry,
                check_cancelled=self._raise_if_stopped,
            )
            if http_client is None
            else http_client
        )
        self.binance = BinanceFuturesClient(
            self.stop_event,
            self.record_symbol_error,
            oi_history_cache_seconds=oi_history_cache_seconds,
            ticker_cache_seconds=ticker_cache_seconds,
            funding_cache_seconds=funding_cache_seconds,
            http_client=self.http_client,
        )
        self.market_caps = CoinGeckoMarketCapClient(
            self.request_json,
            self._wait_for_retry,
            self.record_symbol_error,
            cache_seconds=market_cap_cache_seconds,
            store_path=self.market_cap_file,
        )
        self.market_snapshot_provider = MarketSnapshotProvider(
            self.binance,
            self.market_caps,
            self._raise_if_stopped,
        )
        self.batch_updater = OiBatchUpdater(
            self.binance,
            self.stop_event,
            self.record_symbol_error,
            workers=self.oi_workers,
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
        self.clock = PollerClock(
            row_max_age_seconds=ROW_MAX_AGE_SECONDS,
            clock_skew_seconds=CLOCK_SKEW_SECONDS,
            discontinuity_tolerance_seconds=60,
        )

    def load_previous_cache(self):
        try:
            return load_snapshot_file(self.snapshot_file)
        except (OSError, ValueError, RecursionError) as exc:
            print(f"{timestamp()} failed to load previous OI cache: {exc}")
            return LoadedSnapshot()

    def record_symbol_error(self, symbol, exc):
        if self.error_log.record(symbol, exc):
            print(f"{timestamp()} {symbol} update failed: {exc}")

    def recent_errors(self):
        return self.error_log.recent()

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

    def _raise_if_stopped(self):
        if self.stop_event.is_set():
            raise PollingStopped

    def _wait_for_retry(self, delay):
        if self.stop_event.wait(delay):
            raise PollingStopped

    def request_json(self, url, params=None, timeout=10, attempts=3):
        self._raise_if_stopped()
        return self.http_client.get_json(
            url,
            params=params,
            timeout=timeout,
            attempts=attempts,
        )

    def get_market_tickers(self):
        with self.lock:
            active_symbols = set(self.symbols)
        return self.binance.get_market_tickers(active_symbols)

    def get_funding_rates(self):
        with self.lock:
            active_symbols = set(self.symbols)
        return self.binance.get_funding_rates(active_symbols)

    def get_market_caps(self):
        with self.lock:
            active_symbols = set(self.symbols)
        return self.market_caps.get(active_symbols)

    def get_market_snapshot(self):
        return self.market_snapshot_provider.get(self.active_symbols_snapshot())

    def active_symbols_snapshot(self):
        with self.lock:
            return set(self.symbols)

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
        self.market_caps.retain_symbols(active)

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
        with self.lock:
            if not self.clock.observe_discontinuity(
                wall_now=wall_now,
                monotonic_now=monotonic_now,
            ):
                return False

            self.oi_state.clear()
            self.error_log.clear()
            self.symbol_index = 0
            self.last_symbols_refresh = None
            self.symbols_refresh_retry_at = 0.0
            self.pending_symbols_confirmation = None
            self.last_snapshot_save = None
            self.state = {
                "saved_at": None,
                "error": CLOCK_RESET_ERROR,
            }
            self.clock.clear_success()
            self.binance.clear_caches()
            return True

    def next_batch(self):
        return self.batch_selector.next_batch(self.symbols)

    @property
    def symbol_index(self):
        return self.batch_selector.position

    @symbol_index.setter
    def symbol_index(self, value):
        self.batch_selector.restore(value)

    def update_batch(self, executor=None):
        if self.stop_event.is_set():
            return

        self._reset_after_clock_discontinuity()
        self.refresh_symbols_if_needed()
        if self.stop_event.is_set():
            return
        if not self.symbols:
            return

        market = self.get_market_snapshot()
        batch_start = self.symbol_index
        batch = self.next_batch()
        if not batch:
            return
        try:
            results = self.update_symbols(
                batch,
                market.tickers,
                market.funding_rates,
                market.market_caps,
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
            self.clock.mark_success(saved_at_wall_clock)
            self.state = {
                "saved_at": iso_now(saved_at_wall_clock),
                "error": None,
            }
        self.save_state()

    def update_symbols(self, batch, tickers, funding_rates, market_caps, executor=None):
        return self.batch_updater.update_symbols(
            batch,
            tickers,
            funding_rates,
            market_caps,
            executor=executor,
            build_update=self.build_symbol_update,
        )

    def _update_symbols_parallel(self, batch, tickers, funding_rates, market_caps, executor):
        return self.batch_updater._update_in_parallel(
            batch,
            tickers,
            funding_rates,
            market_caps,
            executor,
            self.build_symbol_update,
        )

    def build_symbol_update(self, symbol, tickers, funding_rates, market_caps=None):
        return self.batch_updater.build_symbol_update(
            symbol,
            tickers,
            funding_rates,
            market_caps,
        )

    def run_forever(self):
        executor = None
        market_cap_thread = None
        try:
            if self.stop_event.is_set():
                return
            market_cap_thread = threading.Thread(
                target=self.market_caps.run_forever,
                args=(self.active_symbols_snapshot,),
                name="market-cap-refresher",
                daemon=True,
            )
            market_cap_thread.start()
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
                if market_cap_thread is not None:
                    market_cap_thread.join(timeout=5)
                    if market_cap_thread.is_alive():
                        print(
                            f"{timestamp()} market-cap refresher did not stop "
                            "within 5 seconds"
                        )
                self._close_after_polling()

    def stop(self):
        """Signal cancellation, then wait for any active state commit to finish."""
        self.stop_event.set()
        with self.lock:
            # Acquiring the lock is the synchronization barrier.
            pass

    def close(self):
        """Release owned network resources after polling has stopped."""
        try:
            self.binance.close()
        finally:
            if self._owns_http_client:
                self.http_client.close()

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
            state["active_symbols"] = list(self.symbols)
            state["total_symbols"] = len(state["active_symbols"])
            state["market_cap_loaded_symbols"] = self.market_caps.count(
                set(state["active_symbols"])
            )
            rows = self.oi_state.copy_rows()
            if rows and self.clock.rows_are_stale(time.time()):
                rows = []
                state["error"] = STALE_ROWS_ERROR
            state["rows"] = rows
            state["recent_errors"] = self.recent_errors()
            return state

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
