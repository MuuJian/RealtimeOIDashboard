"""Coordinate realtime open-interest polling and state."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from math import isfinite
from pathlib import Path

from realtime_oi_dashboard.application.oi.batch_selector import RoundRobinBatchSelector
from realtime_oi_dashboard.infrastructure.binance.futures_client import BinanceFuturesClient
from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient
from realtime_oi_dashboard.infrastructure.coingecko.client import (
    DEFAULT_MARKET_CAP_REFRESH_SECONDS,
    CoinGeckoMarketCapClient,
)
from realtime_oi_dashboard.application.oi.market_snapshot import MarketSnapshotProvider
from realtime_oi_dashboard.application.oi.batch import OIBatchRunner
from realtime_oi_dashboard.application.oi.health import PollerClock, RecentErrorLog
from realtime_oi_dashboard.application.oi.presenter import DashboardPresenter
from realtime_oi_dashboard.application.oi.runtime import DashboardRuntime
from realtime_oi_dashboard.domain.oi.state import OiStateStore
from realtime_oi_dashboard.application.oi.symbol_refresher import SymbolRefresher


DATA_DIR = Path(__file__).resolve().parents[2] / "data"
ROW_MAX_AGE_SECONDS = 15 * 60
CLOCK_SKEW_SECONDS = 60
EMPTY_BATCH_ERROR = "本批次沒有成功更新任何 OI 數據"
CLOCK_RESET_ERROR = "檢測到系統休眠或時鐘跳變，正在重新獲取 OI 數據"
STALE_ROWS_ERROR = "OI 數據已超過 15 分鐘，等待重新獲取"
OI_API_SCHEMA_VERSION = 7


class OIPoller:
    """Facade coordinating the dashboard's focused application services."""

    def __init__(
        self,
        batch_size=25,
        batch_delay=1.0,
        oi_workers=3,
        refresh_symbols_interval=900,
        funding_cache_seconds=3600,
        market_cap_cache_seconds=DEFAULT_MARKET_CAP_REFRESH_SECONDS,
        market_cap_file=None,
        http_client=None,
        shared_rest_cache=None,
    ):
        self.batch_size = _positive_int("batch_size", batch_size)
        self.batch_delay = _non_negative_seconds("batch_delay", batch_delay)
        self.oi_workers = _positive_int("oi_workers", oi_workers)
        self.refresh_symbols_interval = _non_negative_seconds(
            "refresh_symbols_interval",
            refresh_symbols_interval,
        )
        funding_cache_seconds = _non_negative_seconds(
            "funding_cache_seconds",
            funding_cache_seconds,
        )
        market_cap_cache_seconds = _non_negative_seconds(
            "market_cap_cache_seconds",
            market_cap_cache_seconds,
        )
        self.market_cap_file = (
            Path(market_cap_file)
            if market_cap_file
            else DATA_DIR / "market_caps.json"
        )
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.batch_selector = RoundRobinBatchSelector(self.batch_size)
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
            funding_cache_seconds=funding_cache_seconds,
            http_client=self.http_client,
            shared_rest_cache=shared_rest_cache,
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
        self.batch_runner = OIBatchRunner(
            self.binance,
            self.stop_event,
            self.record_symbol_error,
            workers=self.oi_workers,
        )
        self.symbol_refresher = SymbolRefresher(
            self.get_active_symbols,
            self.record_symbol_error,
            self.stop_event,
            self.lock,
            refresh_interval=self.refresh_symbols_interval,
        )
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
        self.presenter = DashboardPresenter(
            self.oi_state,
            self.clock,
            self.recent_errors,
            self.market_caps.count,
            schema_version=OI_API_SCHEMA_VERSION,
            stale_rows_error=STALE_ROWS_ERROR,
        )
        self.runtime = DashboardRuntime(
            self.update_batch,
            self.market_caps.run_forever,
            self.active_symbols_snapshot,
            self._handle_batch_error,
            self.close,
            self.stop_event,
            batch_delay=self.batch_delay,
            workers=self.oi_workers,
            timestamp=timestamp,
        )

    def record_symbol_error(self, symbol, exc):
        if self.error_log.record(symbol, exc):
            print(f"{timestamp()} {symbol} update failed: {exc}")

    def recent_errors(self):
        return self.error_log.recent()

    def get_active_symbols(self, *, force_refresh=False):
        return self.binance.get_active_symbols(force_refresh=force_refresh)

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

    def get_market_snapshot(self):
        return self.market_snapshot_provider.get(self.active_symbols_snapshot())

    def active_symbols_snapshot(self):
        return self.symbol_refresher.active_snapshot()

    def refresh_symbols_if_needed(self):
        return self.symbol_refresher.refresh_if_due(
            self._apply_symbol_refresh,
        )

    def _apply_symbol_refresh(self, refresh):
        if refresh.symbols_changed or self.symbol_index >= len(refresh.symbols):
            self.batch_selector.reset()
        self.prune_inactive_symbols(
            reset_market_caches=refresh.has_new_symbols,
        )

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
            self.batch_selector.reset()
            self.symbol_refresher.reset_schedule()
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

    @property
    def symbols(self):
        return self.symbol_refresher.symbols

    @property
    def known_symbols(self):
        return self.symbol_refresher.known_symbols

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
    def update_symbols(self, batch, tickers, funding_rates, market_caps, executor=None):
        return self.batch_runner.run(
            batch,
            tickers,
            funding_rates,
            market_caps,
            executor=executor,
            build_update=self.build_symbol_update,
        )

    def build_symbol_update(self, symbol, tickers, funding_rates, market_caps=None):
        return self.batch_runner.build_symbol_update(
            symbol,
            tickers,
            funding_rates,
            market_caps,
        )

    def run_forever(self):
        self.runtime.run_forever()

    def _handle_batch_error(self, exc):
        print(f"{timestamp()} batch update failed: {exc}")
        with self.lock:
            self.prune_stale_data()
            self.state["error"] = str(exc)

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

    def get_state(self):
        with self.lock:
            return self.presenter.build(self.state, self.symbols)

def _positive_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _positive_seconds(name, value):
    parsed = _non_negative_seconds(name, value)
    if parsed <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return parsed


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
