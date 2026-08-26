"""Cache shared Binance REST data process-wide with single-flight refresh."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.market_data import (
    MAX_SYMBOL_REMOVAL_FRACTION,
    MIN_EXPECTED_ACTIVE_SYMBOLS,
    parse_active_symbols,
)
from realtime_oi_dashboard.domain.parsing import optional_float
from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol
from realtime_oi_dashboard.infrastructure.binance.market_data import (
    EXCHANGE_INFO_URL,
    TICKER_24H_URL,
    DirectBinanceMarketData,
)
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient


TICKER_URL = TICKER_24H_URL
TICKER_CACHE_SECONDS = 10.0
EXCHANGE_INFO_CACHE_SECONDS = 15 * 60.0
TICKER_STALE_GRACE_SECONDS = 15 * 60.0
EXCHANGE_INFO_STALE_GRACE_SECONDS = 60 * 60.0
TICKER_RETRY_SECONDS = 10.0
EXCHANGE_INFO_RETRY_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 12
REQUEST_ATTEMPTS = 3


@dataclass(slots=True)
class _CacheEntry:
    value: Any = None
    refresh_at: float = 0.0
    stale_at: float = 0.0


class _SharedResource:
    def __init__(
        self,
        load: Callable[[], Any],
        validate: Callable[[object], bool],
        *,
        cache_seconds: float,
        stale_grace_seconds: float,
        retry_seconds: float,
        monotonic: Callable[[], float],
        error_message: str,
        validate_transition: (
            Callable[[object, object | None], bool] | None
        ) = None,
    ) -> None:
        self._load = load
        self._validate = validate
        self._cache_seconds = cache_seconds
        self._stale_grace_seconds = stale_grace_seconds
        self._retry_seconds = retry_seconds
        self._monotonic = monotonic
        self._error_message = error_message
        self._validate_transition = validate_transition
        self._state_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._entry = _CacheEntry()
        self._retry_error = None
        self._retry_error_until = 0.0

    def get(self, *, force_refresh: bool = False):
        cached = None if force_refresh else self._fresh_value()
        if cached is not None:
            return cached

        # Only one caller performs an expired resource refresh. Waiters check
        # the cache again after acquiring the lock and reuse its result.
        with self._refresh_lock:
            cached = None if force_refresh else self._fresh_value()
            if cached is not None:
                return cached

            try:
                value = self._load()
                if not self._validate(value):
                    raise ValueError(self._error_message)
                if (
                    self._validate_transition is not None
                    and not self._validate_transition(
                        value,
                        self._stale_value(),
                    )
                ):
                    raise ValueError(self._error_message)
            except PollingStopped:
                raise
            except Exception as exc:
                # Forced refreshes independently confirm large symbol removals.
                # A stale fallback must not look like a second confirmation.
                if force_refresh:
                    raise
                fallback = self._fallback_value()
                if fallback is not None:
                    return fallback
                self._store_retry_error(exc)
                raise

            now = self._monotonic()
            with self._state_lock:
                self._entry = _CacheEntry(
                    value=value,
                    refresh_at=now + self._cache_seconds,
                    stale_at=(
                        now
                        + self._cache_seconds
                        + self._stale_grace_seconds
                    ),
                )
                self._retry_error = None
                self._retry_error_until = 0.0
            return value

    def _fresh_value(self):
        now = self._monotonic()
        with self._state_lock:
            if (
                self._entry.value is not None
                and now < self._entry.refresh_at
                and now < self._entry.stale_at
            ):
                return self._entry.value
            retry_error = (
                self._retry_error
                if now < self._retry_error_until
                else None
            )
        if retry_error is not None:
            raise retry_error
        return None

    def _fallback_value(self):
        now = self._monotonic()
        with self._state_lock:
            if self._entry.value is None or now >= self._entry.stale_at:
                self._entry = _CacheEntry()
                return None
            self._entry.refresh_at = min(
                now + self._retry_seconds,
                self._entry.stale_at,
            )
            return self._entry.value

    def _stale_value(self):
        now = self._monotonic()
        with self._state_lock:
            if self._entry.value is None or now >= self._entry.stale_at:
                return None
            return self._entry.value

    def _store_retry_error(self, error: Exception) -> None:
        now = self._monotonic()
        with self._state_lock:
            self._retry_error = error
            self._retry_error_until = now + self._retry_seconds


class CachedBinanceMarketData:
    """Share ticker and exchange-info responses across backend pollers."""

    def __init__(
        self,
        *,
        http_client=None,
        source=None,
        exchange_info_cache_seconds: float = EXCHANGE_INFO_CACHE_SECONDS,
        ticker_stale_grace_seconds: float = TICKER_STALE_GRACE_SECONDS,
        exchange_info_stale_grace_seconds: float = (
            EXCHANGE_INFO_STALE_GRACE_SECONDS
        ),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if http_client is not None and source is not None:
            raise TypeError("pass http_client or source, not both")
        if http_client is not None and not callable(
            getattr(http_client, "get_json", None)
        ):
            raise TypeError("http_client must provide a callable get_json")
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")

        exchange_info_cache_seconds = _positive_seconds(
            "exchange_info_cache_seconds",
            exchange_info_cache_seconds,
        )
        ticker_stale_grace_seconds = _non_negative_seconds(
            "ticker_stale_grace_seconds",
            ticker_stale_grace_seconds,
        )
        exchange_info_stale_grace_seconds = _non_negative_seconds(
            "exchange_info_stale_grace_seconds",
            exchange_info_stale_grace_seconds,
        )

        self._owns_http_client = http_client is None and source is None
        self._stop_event = threading.Event()
        self.http_client = None
        if source is None:
            self.http_client = http_client or JsonHttpClient(
                sleep=self._wait_for_retry,
                check_cancelled=self._raise_if_stopped,
            )
            source = DirectBinanceMarketData(
                lambda url, **_kwargs: self._request(url)
            )
        for method_name in ("get_tickers", "get_exchange_info"):
            if not callable(getattr(source, method_name, None)):
                raise TypeError(
                    "source must provide get_tickers and get_exchange_info"
                )
        self._source = source
        self._close_lock = threading.Lock()
        self._closed = False
        self._tickers = _SharedResource(
            self._source.get_tickers,
            _is_ticker_payload,
            cache_seconds=TICKER_CACHE_SECONDS,
            stale_grace_seconds=ticker_stale_grace_seconds,
            retry_seconds=TICKER_RETRY_SECONDS,
            monotonic=monotonic,
            error_message="unexpected ticker response",
            validate_transition=_ticker_transition_is_valid,
        )
        self._exchange_info = _SharedResource(
            self._source.get_exchange_info,
            _is_exchange_info_payload,
            cache_seconds=exchange_info_cache_seconds,
            stale_grace_seconds=exchange_info_stale_grace_seconds,
            retry_seconds=min(
                EXCHANGE_INFO_RETRY_SECONDS,
                exchange_info_cache_seconds,
            ),
            monotonic=monotonic,
            error_message="unexpected exchange-info response",
        )

    def get_tickers(self) -> list:
        self._raise_if_closed()
        self._raise_if_stopped()
        return self._tickers.get()

    def get_exchange_info(self, *, force_refresh: bool = False) -> dict:
        self._raise_if_closed()
        self._raise_if_stopped()
        return self._exchange_info.get(force_refresh=force_refresh)

    def close(self) -> None:
        self.stop()
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        if self._owns_http_client:
            self.http_client.close()

    def stop(self) -> None:
        self._stop_event.set()

    def _request(self, url: str):
        self._raise_if_closed()
        self._raise_if_stopped()
        return self.http_client.get_json(
            url,
            timeout=REQUEST_TIMEOUT_SECONDS,
            attempts=REQUEST_ATTEMPTS,
        )

    def _raise_if_closed(self) -> None:
        with self._close_lock:
            if self._closed:
                raise RuntimeError("Binance REST cache is closed")

    def _raise_if_stopped(self) -> None:
        if self._stop_event.is_set():
            raise PollingStopped

    def _wait_for_retry(self, delay: float) -> None:
        if self._stop_event.wait(delay):
            raise PollingStopped


def _is_ticker_payload(value: object) -> bool:
    response_symbols = _ticker_response_symbols(value)
    return (
        len(response_symbols) == len(set(response_symbols))
        and len(_ticker_symbols(value)) >= MIN_EXPECTED_ACTIVE_SYMBOLS
    )


def _ticker_transition_is_valid(value: object, previous: object | None) -> bool:
    if previous is None:
        return True
    previous_symbols = _ticker_symbols(previous)
    current_symbols = _ticker_symbols(value)
    removed_symbols = previous_symbols - current_symbols
    return len(removed_symbols) <= (
        len(previous_symbols) * MAX_SYMBOL_REMOVAL_FRACTION
    )


def _ticker_symbols(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {
        item["symbol"]
        for item in value
        if isinstance(item, dict)
        and is_valid_binance_symbol(item.get("symbol"))
        and (price := optional_float(item.get("lastPrice"))) is not None
        and price > 0
    }


def _ticker_response_symbols(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item["symbol"]
        for item in value
        if isinstance(item, dict)
        and is_valid_binance_symbol(item.get("symbol"))
    ]


def _is_exchange_info_payload(value: object) -> bool:
    try:
        active_symbols = parse_active_symbols(value)
    except ValueError:
        return False
    return len(active_symbols) >= MIN_EXPECTED_ACTIVE_SYMBOLS


def _positive_seconds(name: str, value: object) -> float:
    parsed = _seconds(name, value, "positive")
    if parsed <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return parsed


# Preserve the established public name while making the decorator role clear.
BinanceRestCache = CachedBinanceMarketData


def _non_negative_seconds(name: str, value: object) -> float:
    parsed = _seconds(name, value, "non-negative")
    if parsed < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return parsed


def _seconds(name: str, value: object, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite {label} number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite {label} number") from exc
    if not isfinite(parsed):
        raise ValueError(f"{name} must be a finite {label} number")
    return parsed
