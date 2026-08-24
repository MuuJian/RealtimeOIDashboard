"""Pure Binance market-response normalization for the realtime OI dashboard."""

from __future__ import annotations

import time

from realtime_oi_dashboard.domain.parsing import optional_float, optional_int
from realtime_oi_dashboard.domain.oi.history_points import MAX_SAFE_INTEGER
from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol


MIN_EXPECTED_ACTIVE_SYMBOLS = 20
MAX_SYMBOL_REMOVAL_FRACTION = 0.2


def parse_active_symbols(response):
    if (
        not isinstance(response, dict)
        or not isinstance(response.get("symbols"), list)
    ):
        raise ValueError("unexpected exchange-info response")

    seen_symbols = set()
    active_symbols = []
    for item in response["symbols"]:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not is_valid_binance_symbol(symbol):
            continue
        if symbol in seen_symbols:
            raise ValueError(f"duplicate exchange-info symbol: {symbol}")
        seen_symbols.add(symbol)
        if (
            item.get("quoteAsset") == "USDT"
            and item.get("status") == "TRADING"
            and item.get("contractType") == "PERPETUAL"
        ):
            active_symbols.append(symbol)

    if not active_symbols:
        raise ValueError("exchange-info response contains no active symbols")
    return sorted(active_symbols)


def parse_market_tickers(response, active_symbols):
    if not isinstance(response, list):
        raise ValueError("unexpected ticker response")

    tickers = {}
    seen_symbols = set()
    for item in response:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not is_valid_binance_symbol(symbol):
            continue
        if active_symbols and symbol not in active_symbols:
            continue
        if symbol in seen_symbols:
            raise ValueError(f"duplicate ticker symbol: {symbol}")
        seen_symbols.add(symbol)

        price = optional_float(item.get("lastPrice"))
        if price is None or price <= 0:
            continue

        volume_24h = optional_float(item.get("quoteVolume"))
        if volume_24h is not None and volume_24h < 0:
            volume_24h = None
        tickers[symbol] = {
            "price": price,
            "volume24h": volume_24h,
            "priceChangePercent": optional_float(item.get("priceChangePercent")),
        }

    if not tickers:
        raise ValueError("ticker response contains no valid symbols")
    return tickers


def validate_symbol_refresh(
    symbols,
    known_symbols,
    *,
    confirmed_large_removal=False,
):
    """Reject undersized lists and unconfirmed large removals."""
    if len(symbols) < MIN_EXPECTED_ACTIVE_SYMBOLS:
        raise ValueError(
            f"exchange-info response contains only {len(symbols)} active symbols"
        )
    if len(known_symbols) < MIN_EXPECTED_ACTIVE_SYMBOLS:
        return

    removed_symbols = set(known_symbols) - set(symbols)
    if (
        not confirmed_large_removal
        and len(removed_symbols)
        > len(known_symbols) * MAX_SYMBOL_REMOVAL_FRACTION
    ):
        raise ValueError(
            "exchange-info response would remove "
            f"{len(removed_symbols)}/{len(known_symbols)} known symbols"
        )


def parse_funding_rates(response, active_symbols, now_ms):
    if isinstance(response, dict):
        response = [response]
    if not isinstance(response, list):
        raise ValueError("unexpected funding-rate response")

    funding_rates = {}
    next_funding_times = []
    seen_symbols = set()
    for item in response:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not is_valid_binance_symbol(symbol):
            continue
        if active_symbols and symbol not in active_symbols:
            continue
        if symbol in seen_symbols:
            raise ValueError(f"duplicate funding-rate symbol: {symbol}")
        seen_symbols.add(symbol)

        funding_rate_percent = optional_float(
            item.get("lastFundingRate"),
            multiplier=100,
        )
        next_funding_time = future_timestamp_ms(item.get("nextFundingTime"), now_ms)
        if funding_rate_percent is None and next_funding_time is None:
            continue
        if next_funding_time is not None:
            next_funding_times.append(next_funding_time)

        funding_rates[symbol] = {
            "fundingRatePercent": funding_rate_percent,
            "nextFundingTime": next_funding_time,
        }

    if not funding_rates:
        raise ValueError("funding-rate response contains no valid symbols")
    return funding_rates, next_funding_times


def incomplete_funding_symbols(funding_rates, active_symbols):
    incomplete_symbols = active_symbols.difference(funding_rates)
    incomplete_symbols.update(
        symbol
        for symbol, funding in funding_rates.items()
        if funding["fundingRatePercent"] is None
        or funding["nextFundingTime"] is None
    )
    return incomplete_symbols


def merge_funding_cache(
    funding_rates,
    next_funding_times,
    cached,
    now_ms,
):
    """Fill fields missing from a partial funding response with usable cache."""

    for symbol, cached_funding in cached.items():
        if not cached_funding:
            continue
        cached_rate = optional_float(cached_funding.get("fundingRatePercent"))
        cached_next_time = future_timestamp_ms(
            cached_funding.get("nextFundingTime"),
            now_ms,
        )

        funding = funding_rates.get(symbol)
        if funding is None:
            if cached_rate is None and cached_next_time is None:
                continue
            funding_rates[symbol] = {
                "fundingRatePercent": cached_rate,
                "nextFundingTime": cached_next_time,
            }
            if cached_next_time is not None:
                next_funding_times.append(cached_next_time)
            continue

        if funding["fundingRatePercent"] is None and cached_rate is not None:
            funding["fundingRatePercent"] = cached_rate
        if funding["nextFundingTime"] is None and cached_next_time is not None:
            funding["nextFundingTime"] = cached_next_time
            next_funding_times.append(cached_next_time)


def future_timestamp_ms(value, now_ms=None):
    parsed = optional_int(value)
    if parsed is None:
        return None
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return parsed if current_ms < parsed <= MAX_SAFE_INTEGER else None
