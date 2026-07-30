"""Best-effort matching between Binance futures symbols and CoinGecko tickers."""

from __future__ import annotations

from typing import Any

from realtime_oi_dashboard.parsing import optional_float

# Order matters: try the longest/most specific prefix first. "1INCH" must
# NOT be caught here — it's a real project ticker, not a multiplier contract.
MULTIPLIER_PREFIXES = ("1000000", "1000", "1M")
QUOTE_ASSET = "USDT"


def normalize_ticker(binance_symbol: str) -> str:
    """Map a Binance perpetual symbol onto the ticker CoinGecko likely uses."""
    base = binance_symbol
    if base.endswith(QUOTE_ASSET):
        base = base[: -len(QUOTE_ASSET)]
    for prefix in MULTIPLIER_PREFIXES:
        if base.startswith(prefix) and len(base) > len(prefix):
            base = base[len(prefix):]
            break
    return base.upper()


def build_market_cap_map(
    coingecko_markets: list[Any],
    active_symbols: set[str],
) -> dict[str, dict[str, float]]:
    """Build a {binance_symbol: {"marketCap": value}} map for active symbols.

    `coingecko_markets` should be in market-cap-descending order (the caller
    requests CoinGecko's `/coins/markets` with `order=market_cap_desc`), so
    when multiple coins share a ticker, the first one seen is the one with
    the larger market cap.
    """
    ticker_to_market_cap: dict[str, float] = {}
    for entry in coingecko_markets:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            continue
        market_cap = optional_float(entry.get("market_cap"))
        if market_cap is None or market_cap <= 0:
            continue
        ticker = symbol.upper()
        if ticker not in ticker_to_market_cap:
            ticker_to_market_cap[ticker] = market_cap

    result: dict[str, dict[str, float]] = {}
    for binance_symbol in active_symbols:
        market_cap = ticker_to_market_cap.get(normalize_ticker(binance_symbol))
        if market_cap is not None:
            result[binance_symbol] = {"marketCap": market_cap}
    return result
