"""Refresh and validate the OI symbol set."""

from __future__ import annotations

import time
from dataclasses import dataclass

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.market_data import validate_symbol_refresh


SYMBOL_REFRESH_RETRY_SECONDS = 60


@dataclass(frozen=True, slots=True)
class SymbolRefresh:
    symbols: list[str]
    symbols_changed: bool
    has_new_symbols: bool


class SymbolRefresher:
    """Own symbol-refresh timing, validation, confirmation, and retry state."""

    def __init__(
        self,
        fetch_symbols,
        record_error,
        stop_event,
        lock,
        *,
        refresh_interval: float,
        known_symbols=None,
        retry_seconds: float = SYMBOL_REFRESH_RETRY_SECONDS,
        monotonic=time.monotonic,
    ) -> None:
        self.fetch_symbols = fetch_symbols
        self.record_error = record_error
        self.stop_event = stop_event
        self.lock = lock
        self.refresh_interval = refresh_interval
        self.retry_seconds = retry_seconds
        self.monotonic = monotonic
        self.symbols: list[str] = []
        self.known_symbols = set(known_symbols or ())
        self.last_refresh = None
        self.retry_at = 0.0
        self.pending_confirmation = None

    def refresh_if_due(self, on_refresh) -> bool:
        now = self.monotonic()
        with self.lock:
            if now < self.retry_at:
                return False
            if (
                self.symbols
                and self.last_refresh is not None
                and now - self.last_refresh < self.refresh_interval
            ):
                return False
            known_symbols = set(self.symbols) or set(self.known_symbols)

        symbols = None
        try:
            symbols = self.fetch_symbols()
            with self.lock:
                confirmed_large_removal = (
                    tuple(symbols) == self.pending_confirmation
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
                    self.pending_confirmation = tuple(symbols)
                can_use_existing = bool(self.symbols)
                self.retry_at = self.monotonic() + self.retry_seconds
            if not can_use_existing:
                raise
            self.record_error("exchangeInfo", exc)
            return False

        with self.lock:
            if self.stop_event.is_set():
                return False
            refresh = SymbolRefresh(
                symbols=symbols,
                symbols_changed=symbols != self.symbols,
                has_new_symbols=bool(set(symbols) - set(self.symbols)),
            )
            self.symbols = symbols
            self.known_symbols = set(symbols)
            self.last_refresh = self.monotonic()
            self.retry_at = 0.0
            self.pending_confirmation = None
            on_refresh(refresh)
            return True

    def active_snapshot(self) -> set[str]:
        with self.lock:
            return set(self.symbols)

    def reset_schedule(self) -> None:
        with self.lock:
            self.last_refresh = None
            self.retry_at = 0.0
            self.pending_confirmation = None
