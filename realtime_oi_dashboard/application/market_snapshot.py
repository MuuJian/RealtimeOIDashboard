"""Collect the shared market data used by one OI polling batch."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    tickers: dict
    funding_rates: dict
    market_caps: dict


class MarketSnapshotProvider:
    """Fetch each shared data source once, in the established order."""

    def __init__(self, binance, market_caps, ensure_running) -> None:
        self.binance = binance
        self.market_caps = market_caps
        self.ensure_running = ensure_running

    def get(self, active_symbols: set[str]) -> MarketSnapshot:
        tickers = self.binance.get_market_tickers(active_symbols)
        self.ensure_running()
        funding_rates = self.binance.get_funding_rates(active_symbols)
        self.ensure_running()
        market_caps = self.market_caps.get(active_symbols)
        self.ensure_running()
        return MarketSnapshot(
            tickers=tickers,
            funding_rates=funding_rates,
            market_caps=market_caps,
        )
