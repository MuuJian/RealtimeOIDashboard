"""Application-facing ports for shared Binance market data."""

from __future__ import annotations

from typing import Protocol


class BinanceMarketDataSource(Protocol):
    """Provide process-wide Binance responses needed by multiple features."""

    def get_tickers(self) -> list:
        """Return the USD-M 24-hour ticker payload."""

    def get_exchange_info(self, *, force_refresh: bool = False) -> dict:
        """Return the USD-M exchange-info payload."""
