"""Market snapshot loading and exchange-info caching for signal scanning."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from math import isfinite
from typing import Any

from realtime_oi_dashboard.domain.errors import PollingStopped


FAPI_BASE_URL = "https://fapi.binance.com"
TICKER_URL = f"{FAPI_BASE_URL}/fapi/v1/ticker/24hr"
EXCHANGE_INFO_URL = f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo"
TICKER_TIMEOUT_SECONDS = 12
EXCHANGE_INFO_TIMEOUT_SECONDS = 12
EXCHANGE_INFO_CACHE_SECONDS = 15 * 60
SIGNAL_SCAN_HTTP_ATTEMPTS = 1


class SignalScanMarketSnapshotLoader:
    """Load all-market tickers and a single-flight exchange-info snapshot."""

    def __init__(
        self,
        request_json: Callable[..., Any],
        stop_event,
        *,
        exchange_info_cache_seconds: float = EXCHANGE_INFO_CACHE_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(request_json):
            raise TypeError("request_json must be callable")
        if not callable(getattr(stop_event, "is_set", None)):
            raise TypeError("stop_event must provide a callable is_set")
        cache_seconds = _positive_seconds(
            "exchange_info_cache_seconds",
            exchange_info_cache_seconds,
        )
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")

        self._request_json = request_json
        self._stop_event = stop_event
        self._cache_seconds = cache_seconds
        self._monotonic = monotonic
        self._cache_lock = threading.Lock()
        self._refresh_lock = threading.Lock()
        self._exchange_info = None
        self._exchange_info_expires_at = 0.0

    def load(self) -> tuple[list, dict]:
        self._raise_if_stopped()
        tickers = self._request_json(
            TICKER_URL,
            timeout=TICKER_TIMEOUT_SECONDS,
            attempts=SIGNAL_SCAN_HTTP_ATTEMPTS,
        )
        if not isinstance(tickers, list):
            raise ValueError("unexpected ticker response")
        self._raise_if_stopped()
        exchange_info = self.load_exchange_info()
        self._raise_if_stopped()
        return tickers, exchange_info

    def load_exchange_info(self) -> dict:
        self._raise_if_stopped()
        cached = self._fresh_exchange_info()
        if cached is not None:
            return cached

        with self._refresh_lock:
            self._raise_if_stopped()
            cached = self._fresh_exchange_info()
            if cached is not None:
                return cached

            exchange_info = self._request_json(
                EXCHANGE_INFO_URL,
                timeout=EXCHANGE_INFO_TIMEOUT_SECONDS,
                attempts=SIGNAL_SCAN_HTTP_ATTEMPTS,
            )
            if not _is_exchange_info_payload(exchange_info):
                raise ValueError("unexpected exchange-info response")

            with self._cache_lock:
                self._raise_if_stopped()
                self._exchange_info = exchange_info
                self._exchange_info_expires_at = (
                    self._monotonic() + self._cache_seconds
                )
            return exchange_info

    def stop(self) -> None:
        """Signal cancellation and wait for any cache write in progress."""
        self._stop_event.set()
        # New operations now fail their event check. Taking the lock waits for
        # any cache write that passed its check before cancellation.
        with self._cache_lock:
            pass

    def peek_exchange_info(self) -> dict | None:
        """Return the cached object for lifecycle diagnostics."""
        with self._cache_lock:
            return self._exchange_info

    def _fresh_exchange_info(self) -> dict | None:
        now = self._monotonic()
        with self._cache_lock:
            self._raise_if_stopped()
            if (
                self._exchange_info is None
                or now >= self._exchange_info_expires_at
            ):
                return None
            return self._exchange_info

    def _raise_if_stopped(self) -> None:
        if self._stop_event.is_set():
            raise PollingStopped


def _is_exchange_info_payload(value: object) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("symbols"), list):
        return False
    return any(
        isinstance(item, dict)
        and isinstance(item.get("symbol"), str)
        and bool(item.get("symbol"))
        and item.get("contractType") == "PERPETUAL"
        and item.get("underlyingType") == "COIN"
        and item.get("status") == "TRADING"
        for item in value["symbols"]
    )


def _positive_seconds(name: str, value: object) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return parsed
