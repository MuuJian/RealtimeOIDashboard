"""Load, validate, and cache the kline history used by signal scanning."""

from __future__ import annotations

from realtime_oi_dashboard.application.signal_scan.kline_cache import (
    SignalScanKlineCache,
)
from realtime_oi_dashboard.application.signal_scan.market_snapshot import (
    FAPI_BASE_URL,
    SIGNAL_SCAN_HTTP_ATTEMPTS,
)
from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.signal_scan.klines import (
    KLINE_MAX_RESPONSE_ROWS,
    merge_kline_history,
    normalize_kline_history,
)
from realtime_oi_dashboard.domain.signal_scan.rules import (
    MIN_CANDLES,
    SCAN_POOL_SIZE,
    classify_symbol,
)


KLINES_URL = f"{FAPI_BASE_URL}/fapi/v1/klines"
KLINE_INTERVAL = "1h"
KLINE_LIMIT = 120
KLINE_REFRESH_LIMIT = 2
KLINE_TIMEOUT_SECONDS = 10
KLINE_CACHE_MAX_SYMBOLS = SCAN_POOL_SIZE * 2


class SignalScanKlineLoader:
    """Own the per-symbol kline request and recovery policy."""

    def __init__(self, request_json, raise_if_stopped, cache: SignalScanKlineCache):
        self._request_json = request_json
        self._raise_if_stopped = raise_if_stopped
        self.cache = cache

    def classify_ticker(self, ticker: dict) -> dict | None:
        symbol = ticker["symbol"]
        klines, used_incremental_cache = self.load(symbol)
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
            klines = self.load_full(symbol)
            self._raise_if_stopped()
            entry = classify_symbol(
                symbol,
                float(ticker["priceChangePercent"]),
                klines,
            )
        if entry is None:
            raise ValueError("invalid kline payload")
        if not self.cache.store(symbol, klines):
            self._raise_if_stopped()
            raise ValueError("invalid kline time series")
        return entry

    def load(self, symbol: str) -> tuple[list, bool]:
        cached = self.cache.get(symbol)
        if cached is None:
            return self.load_full(symbol), False

        try:
            updates = self.request(symbol, limit=KLINE_REFRESH_LIMIT)
        except PollingStopped:
            raise
        except Exception:
            # A failed small refresh must not discard a usable history. Retry
            # once with the full window; the symbol is still marked failed if
            # that recovery request also fails.
            return self.load_full(symbol), False
        merged = merge_kline_history(cached, updates, limit=KLINE_LIMIT)
        if merged is None or len(merged) < MIN_CANDLES:
            return self.load_full(symbol), False
        return merged, True

    def load_full(self, symbol: str) -> list:
        try:
            klines = self.request(symbol, limit=KLINE_LIMIT)
            normalized = normalize_kline_history(klines, limit=KLINE_LIMIT)
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
            self.cache.discard(symbol)
            raise

    def request(self, symbol: str, *, limit: int) -> list:
        return self._request_json(
            KLINES_URL,
            params={
                "symbol": symbol,
                "interval": KLINE_INTERVAL,
                "limit": limit,
            },
            timeout=KLINE_TIMEOUT_SECONDS,
            attempts=SIGNAL_SCAN_HTTP_ATTEMPTS,
        )
