"""Serve OI-specific Binance Futures requests."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.storage.market_cache import MarketCache
from realtime_oi_dashboard.domain.market_data import (
    incomplete_funding_symbols,
    merge_funding_cache,
    parse_funding_rates,
    parse_market_tickers,
)
from realtime_oi_dashboard.application.oi.history import OiHistoryService
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient
from realtime_oi_dashboard.infrastructure.binance.market_data import (
    DirectBinanceMarketData,
    resolve_market_data_source,
)
from realtime_oi_dashboard.domain.parsing import optional_float, optional_int
from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol


PARTIAL_RESPONSE_RETRY_SECONDS = 60
MARKET_CACHE_STALE_GRACE_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class OpenInterestSnapshot:
    """One current OI value and its Binance transaction timestamp."""

    value: float
    timestamp_ms: int


class BinanceFuturesClient:
    """Fetch and cache the Binance data needed by one OI poller."""

    def __init__(
        self,
        stop_event: threading.Event,
        record_error: Callable[[str, Exception], None],
        *,
        funding_cache_seconds: float,
        http_client=None,
        market_data=None,
        shared_rest_cache=None,
    ) -> None:
        self.stop_event = stop_event
        self.record_error = record_error
        self.base_url = "https://fapi.binance.com"
        self.info_url = f"{self.base_url}/fapi/v1/exchangeInfo"
        self.ticker_24h_url = f"{self.base_url}/fapi/v1/ticker/24hr"
        self.funding_url = f"{self.base_url}/fapi/v1/premiumIndex"
        self.oi_url = f"{self.base_url}/fapi/v1/openInterest"
        self.oi_hist_url = f"{self.base_url}/futures/data/openInterestHist"
        self._owns_http_client = http_client is None
        self.http_client = (
            JsonHttpClient(
                sleep=self._wait_for_retry,
                check_cancelled=self._raise_if_stopped,
            )
            if http_client is None
            else http_client
        )
        self.market_data = resolve_market_data_source(
            market_data=market_data,
            legacy_shared_cache=shared_rest_cache,
            direct_factory=lambda: DirectBinanceMarketData(self.request_json),
        )
        self.funding_cache_lock = threading.Lock()
        self.funding_cache = MarketCache(
            funding_cache_seconds,
            MARKET_CACHE_STALE_GRACE_SECONDS,
        )
        self.oi_history = OiHistoryService(
            self._fetch_oi_history,
            record_error,
        )

    def request_json(self, url, params=None, timeout=10, attempts=3):
        self._raise_if_stopped()
        return self.http_client.get_json(
            url,
            params=params,
            timeout=timeout,
            attempts=attempts,
        )

    def _raise_if_stopped(self) -> None:
        if self.stop_event.is_set():
            raise PollingStopped

    def _wait_for_retry(self, delay: float) -> None:
        if self.stop_event.wait(delay):
            raise PollingStopped

    def get_active_symbols(self) -> list[str]:
        data = self.market_data.get_exchange_info()
        self._raise_if_stopped()
        if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
            raise ValueError("unexpected exchange-info response")

        symbols = sorted(
            {
                item["symbol"]
                for item in data.get("symbols", [])
                if isinstance(item, dict)
                and is_valid_binance_symbol(item.get("symbol"))
                and item.get("quoteAsset") == "USDT"
                and item.get("status") == "TRADING"
                and item.get("contractType") == "PERPETUAL"
            }
        )
        if not symbols:
            raise ValueError("exchange-info response contains no active symbols")
        return symbols

    def get_market_tickers(
        self,
        active_symbols: set[str],
    ) -> dict[str, dict[str, float | None]]:
        response = self.market_data.get_tickers()
        self._raise_if_stopped()
        return parse_market_tickers(response, active_symbols)

    def get_funding_rates(
        self,
        active_symbols: set[str],
    ) -> dict[str, dict[str, float | int | None]] | None:
        now = time.monotonic()
        with self.funding_cache_lock:
            lookup = self.funding_cache.get_fresh(now)
            if lookup.hit:
                return lookup.value

        try:
            response = self.request_json(self.funding_url, timeout=12)
            wall_time = time.time()
            now_ms = int(wall_time * 1000)
            funding_rates, next_funding_times = parse_funding_rates(
                response,
                active_symbols,
                now_ms,
            )
            response_time = time.monotonic()
            incomplete_symbols = incomplete_funding_symbols(
                funding_rates, active_symbols
            )
            cached_values = {}
            if incomplete_symbols:
                with self.funding_cache_lock:
                    cached_values = self.funding_cache.copy_for_merge(
                        response_time,
                        incomplete_symbols,
                    )
                merge_funding_cache(
                    funding_rates,
                    next_funding_times,
                    cached_values,
                    now_ms,
                )
            if incomplete_symbols:
                self.record_error(
                    "funding",
                    ValueError(
                        "funding-rate response incomplete for "
                        f"{len(incomplete_symbols)} active symbols"
                    ),
                )
        except PollingStopped:
            raise
        except Exception as exc:
            failure_time = time.monotonic()
            with self.funding_cache_lock:
                fallback = self.funding_cache.fallback_after_failure(
                    failure_time,
                    min(
                        self.funding_cache.cache_seconds,
                        PARTIAL_RESPONSE_RETRY_SECONDS,
                    ),
                    throttle_without_value=True,
                )
            self.record_error("funding", exc)
            return fallback.value if fallback.hit else None

        with self.funding_cache_lock:
            refresh_at = self._next_funding_refresh_at(
                wall_time,
                next_funding_times,
            )
            if incomplete_symbols:
                refresh_at = min(
                    refresh_at,
                    wall_time + PARTIAL_RESPONSE_RETRY_SECONDS,
                )
            self.funding_cache.store(
                funding_rates,
                response_time,
                max(refresh_at - wall_time, 0),
                preserve_stale_deadline=bool(
                    incomplete_symbols and cached_values
                ),
            )
        return funding_rates

    def _next_funding_refresh_at(
        self,
        now: float,
        next_funding_times: list[int],
    ) -> float:
        if self.funding_cache.cache_seconds <= 0:
            return now

        future_times = [
            timestamp_ms / 1000
            for timestamp_ms in next_funding_times
            if timestamp_ms and timestamp_ms / 1000 > now
        ]
        if future_times:
            return min(future_times) + 5

        return now + self.funding_cache.cache_seconds

    def get_open_interest(self, symbol: str) -> OpenInterestSnapshot:
        data = self.request_json(
            self.oi_url,
            params={"symbol": symbol},
            timeout=8,
        )
        value = (
            optional_float(data.get("openInterest"))
            if isinstance(data, dict)
            else None
        )
        timestamp_ms = (
            optional_int(data.get("time"))
            if isinstance(data, dict)
            else None
        )
        if (
            value is None
            or value < 0
            or timestamp_ms is None
            or timestamp_ms <= 0
        ):
            raise ValueError("unexpected open-interest response")
        return OpenInterestSnapshot(value=value, timestamp_ms=timestamp_ms)

    def get_oi_history_changes(
        self,
        symbol: str,
        current_oi: float,
        current_price: float,
        current_timestamp_ms: int,
    ) -> dict[str, float | None]:
        return self.oi_history.get_changes(
            symbol,
            current_oi,
            current_price,
            current_timestamp_ms,
        )

    def _fetch_oi_history(self, symbol: str):
        return self.request_json(
            self.oi_hist_url,
            params={"symbol": symbol, "period": "1h", "limit": 169},
            timeout=10,
        )

    def retain_symbols(
        self,
        active_symbols: set[str],
        *,
        reset_market_caches: bool = False,
    ) -> None:
        self.oi_history.retain_symbols(active_symbols)
        with self.funding_cache_lock:
            if reset_market_caches:
                self.funding_cache.clear()
            else:
                self.funding_cache.retain_symbols(active_symbols)

    def clear_caches(self) -> None:
        self.oi_history.clear()
        with self.funding_cache_lock:
            self.funding_cache.clear()

    def close(self) -> None:
        if self._owns_http_client:
            self.http_client.close()
