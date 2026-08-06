"""Build one dashboard row from Binance and cached market data."""

from __future__ import annotations

import time
from math import isfinite

from realtime_oi_dashboard.market_data import future_timestamp_ms
from realtime_oi_dashboard.oi_state import OiUpdate


class OIRowBuilder:
    """Create one timestamped OI update without managing concurrency or state."""

    def __init__(self, client, stop_event) -> None:
        self.client = client
        self.stop_event = stop_event

    def build(
        self,
        symbol,
        tickers,
        funding_rates,
        market_caps=None,
    ):
        if self.stop_event.is_set():
            return None

        ticker = tickers.get(symbol)
        if not ticker:
            raise ValueError("ticker data unavailable")
        price = ticker["price"]
        volume_24h = ticker["volume24h"]

        current_oi = self.client.get_open_interest(symbol)
        measured_wall_time = time.time()
        measured_at = time.monotonic()
        if self.stop_event.is_set():
            return None

        current_oi_value = current_oi * price
        if not isfinite(current_oi_value):
            raise ValueError("open-interest value is not finite")

        funding = funding_rates.get(symbol, {}) if funding_rates else {}
        funding_rate_percent = funding.get("fundingRatePercent")
        now_ms = int(measured_wall_time * 1000)
        next_funding_time = future_timestamp_ms(
            funding.get("nextFundingTime"),
            now_ms,
        )
        oi_history = self.client.get_oi_history_changes(
            symbol,
            current_oi,
            price,
        )
        market_cap = (market_caps or {}).get(symbol, {}).get("marketCap")

        return OiUpdate(
            symbol=symbol,
            row={
                "symbol": symbol,
                "price": price,
                "volume24h": volume_24h,
                "currentOi": current_oi,
                "currentOiValue": current_oi_value,
                "marketCap": market_cap,
                "oiUpdatedAt": now_ms,
                "priceChangePercent": ticker.get("priceChangePercent"),
                "fundingRatePercent": funding_rate_percent,
                "nextFundingTime": next_funding_time,
                **oi_history,
            },
            measured_at=measured_at,
        )
