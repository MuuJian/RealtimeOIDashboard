"""Build an OI row from already-fetched market data."""

from __future__ import annotations

from math import isfinite

from realtime_oi_dashboard.domain.market_data import future_timestamp_ms
from realtime_oi_dashboard.domain.oi.state import OiUpdate


class OIRowBuilder:
    """Create one timestamped update without network or state side effects."""

    def build(
        self,
        *,
        symbol,
        ticker,
        funding,
        market_cap,
        current_oi,
        oi_history,
        oi_timestamp_ms,
        measured_at,
    ):
        if not ticker:
            raise ValueError("ticker data unavailable")
        price = ticker["price"]
        volume_24h = ticker["volume24h"]

        current_oi_value = current_oi * price
        if not isfinite(current_oi_value):
            raise ValueError("open-interest value is not finite")

        funding = funding or {}
        funding_rate_percent = funding.get("fundingRatePercent")
        next_funding_time = future_timestamp_ms(
            funding.get("nextFundingTime"),
            oi_timestamp_ms,
        )
        return OiUpdate(
            symbol=symbol,
            row={
                "symbol": symbol,
                "price": price,
                "volume24h": volume_24h,
                "currentOi": current_oi,
                "currentOiValue": current_oi_value,
                "marketCap": market_cap,
                "oiUpdatedAt": oi_timestamp_ms,
                "priceChangePercent": ticker.get("priceChangePercent"),
                "fundingRatePercent": funding_rate_percent,
                "nextFundingTime": next_funding_time,
                **(oi_history or {}),
            },
            measured_at=measured_at,
        )
