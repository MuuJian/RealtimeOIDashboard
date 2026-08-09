"""Cache signal-scan klines in process."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from realtime_oi_dashboard.domain.signal_scan.klines import (
    copy_kline_history,
    normalize_kline_history,
)


class SignalScanKlineCache:
    """Own validated history snapshots and least-recently-used eviction."""

    def __init__(
        self,
        stop_event,
        *,
        max_symbols: int,
        history_limit: int,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(getattr(stop_event, "is_set", None)):
            raise TypeError("stop_event must provide a callable is_set")
        if not _is_positive_integer(max_symbols):
            raise ValueError("max_symbols must be a positive integer")
        if not _is_positive_integer(history_limit):
            raise ValueError("history_limit must be a positive integer")
        if not callable(monotonic):
            raise TypeError("monotonic must be callable")

        self._stop_event = stop_event
        self._max_symbols = max_symbols
        self._history_limit = history_limit
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[list, float]] = {}

    def get(self, symbol: str) -> list | None:
        if not _is_symbol_key(symbol) or self._stop_event.is_set():
            return None
        with self._lock:
            if self._stop_event.is_set():
                return None
            cached = self._entries.get(symbol)
            if cached is None:
                return None
            history, _ = cached
            self._entries[symbol] = (history, self._monotonic())
            return copy_kline_history(history)

    def store(self, symbol: str, history: object) -> bool:
        if not _is_symbol_key(symbol) or self._stop_event.is_set():
            return False
        snapshot = normalize_kline_history(
            history,
            limit=self._history_limit,
        )
        if snapshot is None:
            return False

        with self._lock:
            if self._stop_event.is_set():
                return False
            self._entries[symbol] = (snapshot, self._monotonic())
            while len(self._entries) > self._max_symbols:
                oldest_symbol = min(
                    self._entries,
                    key=lambda item: self._entries[item][1],
                )
                self._entries.pop(oldest_symbol, None)
        return True

    def discard(self, symbol: str) -> None:
        if not _is_symbol_key(symbol):
            return
        with self._lock:
            self._entries.pop(symbol, None)

    def stop(self) -> None:
        """Signal cancellation and wait for any cache operation in progress."""
        self._stop_event.set()
        # New operations now fail their event check. Taking the lock waits for
        # any operation that passed its check before cancellation.
        with self._lock:
            pass

    def peek(self, symbol: str) -> list | None:
        """Copy an entry without changing recency or applying stop state."""
        if not _is_symbol_key(symbol):
            return None
        with self._lock:
            cached = self._entries.get(symbol)
            return None if cached is None else copy_kline_history(cached[0])

    def __contains__(self, symbol: object) -> bool:
        if not _is_symbol_key(symbol):
            return False
        with self._lock:
            return symbol in self._entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


def _is_positive_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_symbol_key(value: object) -> bool:
    return isinstance(value, str) and bool(value)
