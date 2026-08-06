"""Pure EMA trend and volatility-spike calculations for signal scanning."""

from __future__ import annotations

import re


STABLE_SYMBOL_PATTERN = re.compile(
    r"^(USDC|FDUSD|TUSD|BUSD|DAI|USDP|USD1|PYUSD|XUSD|USDE|AEUR|RLUSD|EUR|EURI|"
    r"GBP|AUD|JPY|TRY|BRL|ARS|ZAR|MXN|IDRT|NGN|UAH|RUB|PLN|RON|CZK|TRX|BNB|BTC|"
    r"XRP|XAUT|PAXG|XAU|XAG|XPT|XPD|WGOLD|GOLD|SILVER)USDT$"
)

SCAN_POOL_SIZE = 30
TREND_POOL_SIZE = 20
MIN_CANDLES = 60
BULL_BEAR_TOP_N = 8
SPIKE_TOP_N = 10
SPIKE_MIN_VOL_RATIO = 1.8


def compute_ema(values: list[float], period: int) -> float:
    k = 2 / (period + 1)
    ema = values[0]
    for value in values[1:]:
        ema = value * k + ema * (1 - k)
    return ema


def classify_symbol(
    symbol: str,
    price_change_percent: float,
    klines: list[list],
) -> dict | None:
    if len(klines) < MIN_CANDLES:
        return None

    closes = [float(candle[4]) for candle in klines]
    last = closes[-1]
    previous = closes[-2]
    ema20 = compute_ema(closes, 20)
    ema50 = compute_ema(closes, 50)

    amplitudes = [
        (float(candle[2]) - float(candle[3])) / float(candle[4]) * 100
        for candle in klines
    ]
    recent_amplitude = sum(amplitudes[-3:]) / 3
    base_amplitude = sum(amplitudes[-33:-3]) / 30

    return {
        "symbol": symbol,
        "price": last,
        "chg1h": (last / previous - 1) * 100,
        "chg24h": price_change_percent,
        "aboveE20": (last / ema20 - 1) * 100,
        "isBull": last > ema20 > ema50,
        "isBear": last < ema20 < ema50,
        "volRatio": recent_amplitude / base_amplitude if base_amplitude > 0 else 0.0,
    }


def build_scan_universe(
    tickers: list[dict],
    exchange_info: dict,
) -> tuple[list[dict], set[str]]:
    coin_perpetuals = {
        item["symbol"]
        for item in exchange_info.get("symbols", [])
        if isinstance(item, dict)
        and item.get("contractType") == "PERPETUAL"
        and item.get("underlyingType") == "COIN"
        and item.get("status") == "TRADING"
    }

    candidates = [
        ticker
        for ticker in tickers
        if isinstance(ticker, dict)
        and isinstance(ticker.get("symbol"), str)
        and ticker["symbol"].endswith("USDT")
        and "_" not in ticker["symbol"]
        and not STABLE_SYMBOL_PATTERN.match(ticker["symbol"])
        and float(ticker.get("quoteVolume", 0)) > 0
        and ticker["symbol"] in coin_perpetuals
    ]
    candidates.sort(key=lambda ticker: float(ticker["quoteVolume"]), reverse=True)

    scan_pool = candidates[:SCAN_POOL_SIZE]
    trend_pool_symbols = {
        ticker["symbol"] for ticker in scan_pool[:TREND_POOL_SIZE]
    }
    return scan_pool, trend_pool_symbols


def select_signals(entries: list[dict], trend_pool_symbols: set[str]) -> dict:
    trend_entries = [
        entry for entry in entries if entry["symbol"] in trend_pool_symbols
    ]

    bulls = sorted(
        (entry for entry in trend_entries if entry["isBull"]),
        key=lambda entry: entry["aboveE20"],
        reverse=True,
    )[:BULL_BEAR_TOP_N]
    bears = sorted(
        (entry for entry in trend_entries if entry["isBear"]),
        key=lambda entry: entry["aboveE20"],
    )[:BULL_BEAR_TOP_N]
    spikes = sorted(
        (entry for entry in entries if entry["volRatio"] >= SPIKE_MIN_VOL_RATIO),
        key=lambda entry: entry["volRatio"],
        reverse=True,
    )[:SPIKE_TOP_N]

    return {"bulls": bulls, "bears": bears, "spikes": spikes}
