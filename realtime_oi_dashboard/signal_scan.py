"""Signal-scan calculations: EMA trend and volatility-spike detection.

Formula replicated from bubuaplus.com's public client-side JavaScript
(unminified, no auth) — see docs/superpowers/specs/2026-08-03-signal-scan-tab-design.md.
"""

from __future__ import annotations

import re
import threading
import time
from math import isfinite

from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.http import JsonHttpClient
from realtime_oi_dashboard.poller import iso_now, timestamp
from realtime_oi_dashboard.poller_health import RecentErrorLog

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
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def classify_symbol(symbol: str, price_change_percent: float, klines: list[list]) -> dict | None:
    if len(klines) < MIN_CANDLES:
        return None

    closes = [float(c[4]) for c in klines]
    last = closes[-1]
    prev = closes[-2]
    e20 = compute_ema(closes, 20)
    e50 = compute_ema(closes, 50)

    amplitudes = [
        (float(c[2]) - float(c[3])) / float(c[4]) * 100
        for c in klines
    ]
    recent_amplitude = sum(amplitudes[-3:]) / 3
    base_amplitude = sum(amplitudes[-33:-3]) / 30

    return {
        "symbol": symbol,
        "price": last,
        "chg1h": (last / prev - 1) * 100,
        "chg24h": price_change_percent,
        "aboveE20": (last / e20 - 1) * 100,
        "isBull": last > e20 > e50,
        "isBear": last < e20 < e50,
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
    candidates.sort(key=lambda t: float(t["quoteVolume"]), reverse=True)

    scan_pool = candidates[:SCAN_POOL_SIZE]
    trend_pool_symbols = {t["symbol"] for t in scan_pool[:TREND_POOL_SIZE]}
    return scan_pool, trend_pool_symbols


def select_signals(entries: list[dict], trend_pool_symbols: set[str]) -> dict:
    trend_entries = [e for e in entries if e["symbol"] in trend_pool_symbols]

    bulls = sorted(
        (e for e in trend_entries if e["isBull"]),
        key=lambda e: e["aboveE20"],
        reverse=True,
    )[:BULL_BEAR_TOP_N]
    bears = sorted(
        (e for e in trend_entries if e["isBear"]),
        key=lambda e: e["aboveE20"],
    )[:BULL_BEAR_TOP_N]
    spikes = sorted(
        (e for e in entries if e["volRatio"] >= SPIKE_MIN_VOL_RATIO),
        key=lambda e: e["volRatio"],
        reverse=True,
    )[:SPIKE_TOP_N]

    return {"bulls": bulls, "bears": bears, "spikes": spikes}


FAPI_BASE_URL = "https://fapi.binance.com"
TICKER_URL = f"{FAPI_BASE_URL}/fapi/v1/ticker/24hr"
EXCHANGE_INFO_URL = f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo"
KLINES_URL = f"{FAPI_BASE_URL}/fapi/v1/klines"

SCAN_MAX_AGE_SECONDS = 90
SIGNAL_SCAN_API_SCHEMA_VERSION = 1
SCAN_FAILED_ERROR = "本次掃描沒有取得任何幣種資料"


class SignalScanPoller:
    """Poll Binance and recompute the bubuaplus.com-equivalent signals."""

    def __init__(self, *, interval_seconds=60, http_client=None):
        self.interval_seconds = _positive_seconds("interval_seconds", interval_seconds)
        self.max_age_seconds = max(SCAN_MAX_AGE_SECONDS, self.interval_seconds * 1.5)
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self._owns_http_client = http_client is None
        self.http_client = (
            JsonHttpClient(
                sleep=self._wait_for_retry,
                check_cancelled=self._raise_if_stopped,
            )
            if http_client is None
            else http_client
        )
        self.error_log = RecentErrorLog(self.stop_event)
        self.last_success_wall_clock = None
        self.state = {
            "bulls": [],
            "bears": [],
            "spikes": [],
            "saved_at": None,
            "error": None,
        }

    def _raise_if_stopped(self):
        if self.stop_event.is_set():
            raise PollingStopped

    def _wait_for_retry(self, delay):
        if self.stop_event.wait(delay):
            raise PollingStopped

    def request_json(self, url, params=None, timeout=10, attempts=3):
        self._raise_if_stopped()
        return self.http_client.get_json(
            url, params=params, timeout=timeout, attempts=attempts
        )

    def run_scan(self):
        tickers = self.request_json(TICKER_URL, timeout=12)
        exchange_info = self.request_json(EXCHANGE_INFO_URL, timeout=12)
        scan_pool, trend_pool_symbols = build_scan_universe(tickers, exchange_info)

        if not scan_pool:
            with self.lock:
                self.state["error"] = SCAN_FAILED_ERROR
            return

        entries = []
        for ticker in scan_pool:
            symbol = ticker["symbol"]
            try:
                klines = self.request_json(
                    KLINES_URL,
                    params={"symbol": symbol, "interval": "1h", "limit": 120},
                    timeout=10,
                )
                entry = classify_symbol(
                    symbol, float(ticker["priceChangePercent"]), klines
                )
            except PollingStopped:
                raise
            except Exception as exc:
                self.record_symbol_error(symbol, exc)
                continue
            if entry is not None:
                entries.append(entry)

        if not entries:
            with self.lock:
                self.state["error"] = SCAN_FAILED_ERROR
            return

        signals = select_signals(entries, trend_pool_symbols)
        with self.lock:
            self.last_success_wall_clock = time.time()
            self.state = {
                "bulls": signals["bulls"],
                "bears": signals["bears"],
                "spikes": signals["spikes"],
                "saved_at": iso_now(self.last_success_wall_clock),
                "error": None,
            }

    def record_symbol_error(self, symbol, exc):
        if self.error_log.record(symbol, exc):
            print(f"{timestamp()} signal scan {symbol} failed: {exc}")

    def run_forever(self):
        while not self.stop_event.is_set():
            try:
                self.run_scan()
            except PollingStopped:
                break
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                print(f"{timestamp()} signal scan failed: {exc}")
                with self.lock:
                    self.state["error"] = str(exc)
            self.stop_event.wait(self.interval_seconds)
        self._close_after_polling()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            pass

    def close(self):
        if self._owns_http_client:
            self.http_client.close()

    def _close_after_polling(self):
        try:
            self.close()
        except Exception as exc:
            print(f"{timestamp()} failed to close signal scan poller: {exc}")

    def get_state(self):
        with self.lock:
            state = dict(self.state)
            state["schema_version"] = SIGNAL_SCAN_API_SCHEMA_VERSION
            state["recent_errors"] = self.error_log.recent()
            if state["saved_at"] is not None and self._is_stale():
                state["bulls"] = []
                state["bears"] = []
                state["spikes"] = []
                state["error"] = (
                    f"訊號資料已超過 {int(self.max_age_seconds)} 秒，等待重新掃描"
                )
            return state

    def _is_stale(self):
        if self.last_success_wall_clock is None:
            return True
        age = time.time() - self.last_success_wall_clock
        return not isfinite(age) or age > self.max_age_seconds


def _positive_seconds(name, value):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite positive number") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a finite positive number")
    return parsed
