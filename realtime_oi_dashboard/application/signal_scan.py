"""Background polling and state publication for signal scanning."""

from __future__ import annotations

import threading
import time
from math import isfinite

from realtime_oi_dashboard.application.poller import iso_now, timestamp
from realtime_oi_dashboard.application.poller_health import RecentErrorLog
from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.signal_scan import (
    build_scan_universe,
    classify_symbol,
    select_signals,
)
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient


FAPI_BASE_URL = "https://fapi.binance.com"
TICKER_URL = f"{FAPI_BASE_URL}/fapi/v1/ticker/24hr"
EXCHANGE_INFO_URL = f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo"
KLINES_URL = f"{FAPI_BASE_URL}/fapi/v1/klines"

SCAN_MAX_AGE_SECONDS = 90
SIGNAL_SCAN_API_SCHEMA_VERSION = 1
SCAN_FAILED_ERROR = "本次掃描沒有取得任何幣種資料"


class SignalScanPoller:
    """Poll Binance and recompute the bubuaplus.com-equivalent signals."""

    def __init__(self, *, interval_seconds=60, http_client=None):
        self.interval_seconds = _positive_seconds("interval_seconds", interval_seconds)
        self.max_age_seconds = max(SCAN_MAX_AGE_SECONDS, self.interval_seconds * 1.5)
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
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
        self.last_success_wall_clock = None
        self.state = {
            "bulls": [],
            "bears": [],
            "spikes": [],
            "saved_at": None,
            "error": None,
        }

    def _raise_if_stopped(self):
        if self.stop_event.is_set():
            raise PollingStopped

    def _wait_for_retry(self, delay):
        if self.stop_event.wait(delay):
            raise PollingStopped

    def request_json(self, url, params=None, timeout=10, attempts=3):
        self._raise_if_stopped()
        return self.http_client.get_json(
            url, params=params, timeout=timeout, attempts=attempts
        )

    def run_scan(self):
        tickers = self.request_json(TICKER_URL, timeout=12)
        exchange_info = self.request_json(EXCHANGE_INFO_URL, timeout=12)
        scan_pool, trend_pool_symbols = build_scan_universe(tickers, exchange_info)

        if not scan_pool:
            with self.lock:
                self.state["error"] = SCAN_FAILED_ERROR
            return

        entries = []
        for ticker in scan_pool:
            symbol = ticker["symbol"]
            try:
                klines = self.request_json(
                    KLINES_URL,
                    params={"symbol": symbol, "interval": "1h", "limit": 120},
                    timeout=10,
                )
                entry = classify_symbol(
                    symbol, float(ticker["priceChangePercent"]), klines
                )
            except PollingStopped:
                raise
            except Exception as exc:
                self.record_symbol_error(symbol, exc)
                continue
            if entry is not None:
                entries.append(entry)

        if not entries:
            with self.lock:
                self.state["error"] = SCAN_FAILED_ERROR
            return

        signals = select_signals(entries, trend_pool_symbols)
        with self.lock:
            self.last_success_wall_clock = time.time()
            self.state = {
                "bulls": signals["bulls"],
                "bears": signals["bears"],
                "spikes": signals["spikes"],
                "saved_at": iso_now(self.last_success_wall_clock),
                "error": None,
            }

    def record_symbol_error(self, symbol, exc):
        if self.error_log.record(symbol, exc):
            print(f"{timestamp()} signal scan {symbol} failed: {exc}")

    def run_forever(self):
        while not self.stop_event.is_set():
            try:
                self.run_scan()
            except PollingStopped:
                break
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                print(f"{timestamp()} signal scan failed: {exc}")
                with self.lock:
                    self.state["error"] = str(exc)
            self.stop_event.wait(self.interval_seconds)
        self._close_after_polling()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            pass

    def close(self):
        if self._owns_http_client:
            self.http_client.close()

    def _close_after_polling(self):
        try:
            self.close()
        except Exception as exc:
            print(f"{timestamp()} failed to close signal scan poller: {exc}")

    def get_state(self):
        with self.lock:
            state = dict(self.state)
            state["schema_version"] = SIGNAL_SCAN_API_SCHEMA_VERSION
            state["recent_errors"] = self.error_log.recent()
            if state["saved_at"] is not None and self._is_stale():
                state["bulls"] = []
                state["bears"] = []
                state["spikes"] = []
                state["error"] = (
                    f"訊號資料已超過 {int(self.max_age_seconds)} 秒，等待重新掃描"
                )
            return state

    def _is_stale(self):
        if self.last_success_wall_clock is None:
            return True
        age = time.time() - self.last_success_wall_clock
        return not isfinite(age) or age > self.max_age_seconds


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
