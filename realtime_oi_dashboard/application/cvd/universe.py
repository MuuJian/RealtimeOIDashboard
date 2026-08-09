"""Discover the active CVD contract universe."""

from __future__ import annotations

import time
from dataclasses import dataclass

from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol


CVD_UNIVERSE_REFRESH_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class UniverseChange:
    symbols: frozenset[str]
    added: frozenset[str]
    removed: frozenset[str]
    changed: bool


class CvdUniverseManager:
    def __init__(
        self,
        load_exchange_info,
        *,
        refresh_seconds=CVD_UNIVERSE_REFRESH_SECONDS,
        monotonic=time.monotonic,
    ) -> None:
        self._load_exchange_info = load_exchange_info
        self._refresh_seconds = float(refresh_seconds)
        self._monotonic = monotonic
        self._symbols: set[str] = set()
        self._next_refresh_at = 0.0
        self.last_error: str | None = None

    def refresh_if_due(self, *, force=False) -> UniverseChange | None:
        now = self._monotonic()
        if not force and now < self._next_refresh_at:
            return None
        try:
            symbols = select_cvd_symbols(self._load_exchange_info())
            if not symbols:
                raise ValueError("exchangeInfo contains no active USDT perpetuals")
        except Exception as exc:
            self.last_error = str(exc)
            self._next_refresh_at = now + min(self._refresh_seconds, 60.0)
            if self._symbols:
                return UniverseChange(
                    frozenset(self._symbols),
                    frozenset(),
                    frozenset(),
                    False,
                )
            raise

        added = symbols - self._symbols
        removed = self._symbols - symbols
        self._symbols = symbols
        self._next_refresh_at = now + self._refresh_seconds
        self.last_error = None
        return UniverseChange(
            frozenset(symbols),
            frozenset(added),
            frozenset(removed),
            bool(added or removed),
        )

    @property
    def symbols(self) -> set[str]:
        return set(self._symbols)


def select_cvd_symbols(exchange_info) -> set[str]:
    if not isinstance(exchange_info, dict):
        return set()
    entries = exchange_info.get("symbols")
    if not isinstance(entries, list):
        return set()
    return {
        item["symbol"]
        for item in entries
        if isinstance(item, dict)
        and is_valid_binance_symbol(item.get("symbol"))
        and item.get("status") == "TRADING"
        and item.get("contractType") == "PERPETUAL"
        and item.get("quoteAsset") == "USDT"
    }
