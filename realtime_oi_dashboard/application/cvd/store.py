"""Store CVD windows and publish immutable snapshots."""

from __future__ import annotations

import threading
from types import MappingProxyType

from realtime_oi_dashboard.domain.cvd.model import MINUTE_MS, SymbolCvdWindow


class CvdStore:
    def __init__(self, *, now_ms) -> None:
        self._now_ms = now_ms
        self._registry_lock = threading.RLock()
        self._windows: dict[str, SymbolCvdWindow] = {}
        self._active_symbols: set[str] = set()
        self._published = MappingProxyType({})

    def set_universe(self, symbols: set[str]) -> tuple[set[str], set[str]]:
        symbols = set(symbols)
        with self._registry_lock:
            added = symbols - self._active_symbols
            removed = self._active_symbols - symbols
            for symbol in added:
                self._windows.setdefault(symbol, SymbolCvdWindow(symbol))
            for symbol in set(self._windows).difference(symbols):
                self._windows.pop(symbol, None)
            self._active_symbols = symbols
            return added, removed

    def update_bucket(self, symbol: str, **bucket) -> bool:
        with self._registry_lock:
            if symbol not in self._active_symbols:
                return False
            window = self._windows[symbol]
        return window.update(**bucket)

    def set_connected(
        self,
        symbols: set[str],
        connected: bool,
        reason: str | None = None,
    ) -> None:
        with self._registry_lock:
            windows = [
                self._windows[symbol]
                for symbol in symbols
                if symbol in self._active_symbols and symbol in self._windows
            ]
        for window in windows:
            window.set_connected(connected, reason)

    def mark_partial(self, symbol: str, reason: str) -> None:
        with self._registry_lock:
            window = self._windows.get(symbol)
        if window is not None:
            window.mark_partial(reason)

    def fill_closed_zero_buckets(self, symbols: set[str], *, now_ms: int) -> None:
        previous_open = now_ms // MINUTE_MS * MINUTE_MS - MINUTE_MS
        with self._registry_lock:
            windows = [
                self._windows[symbol]
                for symbol in symbols
                if symbol in self._active_symbols and symbol in self._windows
            ]
        for window in windows:
            window.ensure_zero(previous_open, updated_at=now_ms)

    def missing_recent_buckets(
        self,
        symbol: str,
        *,
        now_ms: int,
        minutes: int = 16,
    ) -> list[int]:
        with self._registry_lock:
            window = self._windows.get(symbol)
        if window is None:
            return []
        current_open = now_ms // MINUTE_MS * MINUTE_MS
        return [
            current_open - offset * MINUTE_MS
            for offset in range(minutes)
            if not window.has_open_time(current_open - offset * MINUTE_MS)
        ]

    def publish(self, *, now_ms: int | None = None) -> MappingProxyType:
        current_ms = self._now_ms() if now_ms is None else now_ms
        with self._registry_lock:
            items = [
                (symbol, self._windows[symbol])
                for symbol in sorted(self._active_symbols)
            ]
        rows = {symbol: window.snapshot(now_ms=current_ms) for symbol, window in items}
        published = MappingProxyType(rows)
        with self._registry_lock:
            self._published = published
        return published

    def published(self) -> dict:
        with self._registry_lock:
            return dict(self._published)

    def export(self, *, cutoff_ms: int) -> dict[str, list[dict]]:
        with self._registry_lock:
            items = list(self._windows.items())
        return {
            symbol: buckets
            for symbol, window in items
            if (buckets := window.export_buckets(cutoff_ms=cutoff_ms))
        }

    def restore(self, records: dict[str, list[dict]], *, updated_at: int) -> int:
        restored = 0
        with self._registry_lock:
            for symbol in records:
                self._windows.setdefault(symbol, SymbolCvdWindow(symbol))
        for symbol, buckets in records.items():
            window = self._windows[symbol]
            for bucket in buckets:
                if window.update(
                    open_time=bucket.get("openTime"),
                    quote_volume=bucket.get("quoteVolume"),
                    taker_buy_quote_volume=bucket.get("takerBuyQuoteVolume"),
                    closed=bool(bucket.get("closed")),
                    source="snapshot",
                    updated_at=updated_at,
                ):
                    restored += 1
        return restored

    def active_symbols(self) -> set[str]:
        with self._registry_lock:
            return set(self._active_symbols)
