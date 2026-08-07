"""Pure EMA trend and volatility-spike calculations for signal scanning."""

from __future__ import annotations

from collections.abc import Sequence, Set
from math import isfinite
import re


STABLE_SYMBOL_PATTERN = re.compile(
    r"^(USDC|FDUSD|TUSD|BUSD|DAI|USDP|USD1|PYUSD|XUSD|USDE|AEUR|RLUSD|EUR|EURI|"
    r"GBP|AUD|JPY|TRY|BRL|ARS|ZAR|MXN|IDRT|NGN|UAH|RUB|PLN|RON|CZK|TRX|BNB|BTC|"
    r"XRP|XAUT|PAXG|XAU|XAG|XPT|XPD|WGOLD|GOLD|SILVER)USDT$"
)
USDT_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+USDT$")

SCAN_POOL_SIZE = 30
TREND_POOL_SIZE = 20
MIN_CANDLES = 60
BULL_BEAR_TOP_N = 8
SPIKE_TOP_N = 10
SPIKE_MIN_VOL_RATIO = 1.8
KLINE_CLOSE_INDEX = 4
KLINE_HIGH_INDEX = 2
KLINE_LOW_INDEX = 3


def compute_ema(values: Sequence[float], period: int) -> float:
    if isinstance(period, bool) or not isinstance(period, int) or period <= 0:
        raise ValueError("EMA period must be a positive integer")
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError("EMA requires a numeric sequence")
    if not len(values):
        raise ValueError("EMA requires at least one value")

    first = _finite_float(values[0])
    if first is None:
        raise ValueError("EMA values must be finite numbers")

    k = 2 / (period + 1)
    ema = first
    for raw_value in values[1:]:
        value = _finite_float(raw_value)
        if value is None:
            raise ValueError("EMA values must be finite numbers")
        ema = value * k + ema * (1 - k)
    return ema


def classify_symbol(
    symbol: str,
    price_change_percent: float,
    klines: Sequence[Sequence],
) -> dict | None:
    if (
        not isinstance(symbol, str)
        or USDT_SYMBOL_PATTERN.fullmatch(symbol) is None
    ):
        return None
    if not isinstance(klines, Sequence) or isinstance(klines, (str, bytes)):
        return None
    if len(klines) < MIN_CANDLES:
        return None

    parsed_candles = _parse_candles(klines)
    if parsed_candles is None:
        return None

    price_change = _finite_float(price_change_percent)
    if price_change is None:
        return None

    closes = [candle[2] for candle in parsed_candles]
    last = closes[-1]
    previous = closes[-2]
    if previous <= 0:
        return None

    ema20 = compute_ema(closes, 20)
    ema50 = compute_ema(closes, 50)
    if not isfinite(ema20) or not isfinite(ema50):
        return None

    amplitudes = [
        (high - low) / close * 100
        for high, low, close in parsed_candles
    ]
    if not all(isfinite(value) for value in amplitudes):
        return None
    recent_amplitude = sum(amplitudes[-3:]) / 3
    base_amplitude = sum(amplitudes[-33:-3]) / 30
    if not isfinite(recent_amplitude) or not isfinite(base_amplitude):
        return None
    chg1h = (last / previous - 1) * 100
    above_e20 = (last / ema20 - 1) * 100
    vol_ratio = recent_amplitude / base_amplitude if base_amplitude > 0 else 0.0
    if not all(isfinite(value) for value in (chg1h, above_e20, vol_ratio)):
        return None

    return {
        "symbol": symbol,
        "price": last,
        "chg1h": chg1h,
        "chg24h": price_change,
        "aboveE20": above_e20,
        "isBull": last > ema20 > ema50,
        "isBear": last < ema20 < ema50,
        "volRatio": vol_ratio,
    }


def build_scan_universe(
    tickers: Sequence[dict],
    exchange_info: dict,
) -> tuple[list[dict], set[str]]:
    if not isinstance(tickers, Sequence) or isinstance(tickers, (str, bytes)):
        return [], set()
    if not isinstance(exchange_info, dict):
        return [], set()

    exchange_symbols = exchange_info.get("symbols", [])
    if not isinstance(exchange_symbols, Sequence) or isinstance(
        exchange_symbols,
        (str, bytes),
    ):
        exchange_symbols = []

    coin_perpetuals = {
        item["symbol"]
        for item in exchange_symbols
        if isinstance(item, dict)
        and isinstance(item.get("symbol"), str)
        and item.get("contractType") == "PERPETUAL"
        and item.get("underlyingType") == "COIN"
        and item.get("status") == "TRADING"
    }

    candidates_by_symbol = {}
    for ticker in tickers:
        if not isinstance(ticker, dict):
            continue
        symbol = ticker.get("symbol")
        quote_volume = _finite_float(ticker.get("quoteVolume"))
        price_change = _finite_float(ticker.get("priceChangePercent"))
        if (
            not isinstance(symbol, str)
            or USDT_SYMBOL_PATTERN.fullmatch(symbol) is None
            or STABLE_SYMBOL_PATTERN.fullmatch(symbol) is not None
            or quote_volume is None
            or quote_volume <= 0
            or price_change is None
            or symbol not in coin_perpetuals
        ):
            continue
        previous = candidates_by_symbol.get(symbol)
        if previous is None or quote_volume > previous[0]:
            candidates_by_symbol[symbol] = (quote_volume, ticker)

    candidates = list(candidates_by_symbol.values())
    candidates.sort(key=lambda item: (-item[0], item[1]["symbol"]))

    scan_pool = [ticker for _, ticker in candidates[:SCAN_POOL_SIZE]]
    trend_pool_symbols = {
        ticker["symbol"] for ticker in scan_pool[:TREND_POOL_SIZE]
    }
    return scan_pool, trend_pool_symbols


def filter_signal_entries(entries: Sequence[dict]) -> list[dict]:
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return []

    valid_entries = []
    seen_symbols = set()
    for entry in entries:
        if not _is_signal_entry(entry):
            continue
        symbol = entry["symbol"]
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        valid_entries.append(entry)
    return valid_entries


def select_signals(entries: list[dict], trend_pool_symbols: set[str]) -> dict:
    valid_entries = filter_signal_entries(entries)
    if not isinstance(trend_pool_symbols, Set):
        trend_pool_symbols = set()

    trend_entries = [
        entry for entry in valid_entries if entry["symbol"] in trend_pool_symbols
    ]

    bulls = sorted(
        (entry for entry in trend_entries if entry["isBull"]),
        key=lambda entry: (-entry["aboveE20"], entry["symbol"]),
    )[:BULL_BEAR_TOP_N]
    bears = sorted(
        (entry for entry in trend_entries if entry["isBear"]),
        key=lambda entry: (entry["aboveE20"], entry["symbol"]),
    )[:BULL_BEAR_TOP_N]
    spikes = sorted(
        (
            entry
            for entry in valid_entries
            if entry["volRatio"] >= SPIKE_MIN_VOL_RATIO
        ),
        key=lambda entry: (-entry["volRatio"], entry["symbol"]),
    )[:SPIKE_TOP_N]

    return {"bulls": bulls, "bears": bears, "spikes": spikes}


def _is_signal_entry(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if (
        not isinstance(value.get("symbol"), str)
        or USDT_SYMBOL_PATTERN.fullmatch(value["symbol"]) is None
        or not isinstance(value.get("isBull"), bool)
        or not isinstance(value.get("isBear"), bool)
        or value["isBull"] and value["isBear"]
    ):
        return False
    price = _signal_number(value.get("price"))
    if price is None or price <= 0:
        return False
    for field in ("chg1h", "chg24h", "aboveE20"):
        if _signal_number(value.get(field)) is None:
            return False
    vol_ratio = _signal_number(value.get("volRatio"))
    return vol_ratio is not None and vol_ratio >= 0


def _parse_candles(klines: Sequence[Sequence]) -> list[tuple[float, float, float]] | None:
    parsed = []
    for candle in klines:
        if not isinstance(candle, Sequence) or isinstance(candle, (str, bytes)):
            return None
        if len(candle) <= KLINE_CLOSE_INDEX:
            return None

        high = _finite_float(candle[KLINE_HIGH_INDEX])
        low = _finite_float(candle[KLINE_LOW_INDEX])
        close = _finite_float(candle[KLINE_CLOSE_INDEX])
        if (
            high is None
            or low is None
            or close is None
            or high < low
            or low < 0
            or close <= 0
            or close < low
            or close > high
        ):
            return None
        parsed.append((high, low, close))
    return parsed


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


def _signal_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None
