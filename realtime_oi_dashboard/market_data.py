"""Pure Binance market-response normalization for the realtime OI dashboard."""

from __future__ import annotations

import time
from math import isfinite

from realtime_oi_dashboard.parsing import optional_float, optional_int
from realtime_oi_dashboard.symbols import is_valid_binance_symbol


MIN_EXPECTED_ACTIVE_SYMBOLS = 20
MAX_SYMBOL_REMOVAL_FRACTION = 0.2
MAX_SAFE_INTEGER = 2**53 - 1
HOUR_MS = 60 * 60 * 1000
HISTORY_BASELINE_TOLERANCE_MS = 2 * HOUR_MS


def parse_market_tickers(response, active_symbols):
    if not isinstance(response, list):
        raise ValueError("unexpected ticker response")

    tickers = {}
    for item in response:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        price = optional_float(item.get("lastPrice"))
        if not is_valid_binance_symbol(symbol) or price is None or price <= 0:
            continue
        if active_symbols and symbol not in active_symbols:
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
    for item in response:
        if not isinstance(item, dict):
            continue
        symbol = item.get("symbol")
        if not is_valid_binance_symbol(symbol):
            continue
        if active_symbols and symbol not in active_symbols:
            continue

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


def incomplete_market_ticker_symbols(tickers, active_symbols):
    incomplete_symbols = active_symbols.difference(tickers)
    incomplete_symbols.update(
        symbol
        for symbol, ticker in tickers.items()
        if ticker["volume24h"] is None
        or ticker["priceChangePercent"] is None
    )
    return incomplete_symbols


def merge_market_ticker_cache(tickers, cached):
    """Fill fields missing from a partial ticker response with usable cache."""

    for symbol, cached_ticker in cached.items():
        if not cached_ticker:
            continue
        ticker = tickers.get(symbol)
        if ticker is None:
            tickers[symbol] = dict(cached_ticker)
            continue
        for field in ("volume24h", "priceChangePercent"):
            if ticker[field] is not None:
                continue
            cached_value = optional_float(cached_ticker.get(field))
            if cached_value is not None:
                ticker[field] = cached_value


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


def parse_oi_history_points(response):
    if not isinstance(response, list):
        raise ValueError("unexpected OI history response")

    history_points = []
    for item in response:
        if not isinstance(item, dict):
            continue
        timestamp_ms = optional_int(item.get("timestamp"))
        if timestamp_ms is None or timestamp_ms <= 0:
            continue
        history_points.append((timestamp_ms, item))
    history_points.sort(key=lambda point: point[0])
    return history_points


def history_open_interest_point(history_points, target_timestamp_ms, label):
    """Return the nearest usable OI and implied price at or before a target."""
    saw_invalid_value = False
    for timestamp_ms, item in reversed(history_points):
        if timestamp_ms > target_timestamp_ms:
            continue
        if target_timestamp_ms - timestamp_ms > HISTORY_BASELINE_TOLERANCE_MS:
            break

        open_interest = optional_float(item.get("sumOpenInterest"))
        if open_interest is None or open_interest < 0:
            saw_invalid_value = True
            continue
        return timestamp_ms, open_interest, _history_implied_price(
            item,
            open_interest,
        )

    if saw_invalid_value:
        raise ValueError(f"invalid {label} OI history")
    return None


def history_point_value(point, target_timestamp_ms):
    """Return a cached history value only while its source remains in range."""
    if not _history_point_is_usable(point, target_timestamp_ms):
        return None
    return point[1]


def history_point_price(point, target_timestamp_ms):
    """Return the implied historical price while its source remains in range."""
    if not _history_point_is_usable(point, target_timestamp_ms):
        return None
    return point[2]


def _history_point_is_usable(point, target_timestamp_ms):
    if point is None:
        return False
    timestamp_ms = point[0]
    return (
        timestamp_ms <= target_timestamp_ms
        and target_timestamp_ms - timestamp_ms
        <= HISTORY_BASELINE_TOLERANCE_MS
    )


def _history_implied_price(item, open_interest):
    if open_interest <= 0:
        return None
    open_interest_value = optional_float(item.get("sumOpenInterestValue"))
    if open_interest_value is None or open_interest_value <= 0:
        return None
    price = open_interest_value / open_interest
    return price if isfinite(price) and price > 0 else None


def calculate_change_percent(current_value, previous_value):
    if previous_value is None or previous_value <= 0:
        return None
    change_percent = (current_value - previous_value) / previous_value * 100
    return change_percent if isfinite(change_percent) else None


def future_timestamp_ms(value, now_ms=None):
    parsed = optional_int(value)
    if parsed is None:
        return None
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return parsed if current_ms < parsed <= MAX_SAFE_INTEGER else None
