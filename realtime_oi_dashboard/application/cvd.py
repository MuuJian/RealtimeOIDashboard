"""Background Binance aggregated-trade polling for CVD snapshots."""

from __future__ import annotations

import json
import threading
import time
from math import isfinite

import websocket

from realtime_oi_dashboard.domain.cvd import RollingCvdWindow
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient


FAPI_BASE_URL = "https://fapi.binance.com"
TICKER_URL = f"{FAPI_BASE_URL}/fapi/v1/ticker/24hr"
EXCHANGE_INFO_URL = f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo"
KLINES_URL = f"{FAPI_BASE_URL}/fapi/v1/klines"
STREAM_BASE_URL = "wss://fstream.binance.com/stream?streams="


class CvdPoller:
    """Publish rolling CVD for a bounded universe of liquid futures symbols."""

    def __init__(
        self,
        *,
        interval_seconds=60,
        max_symbols=30,
        http_client=None,
        websocket_factory=None,
        now_ms=None,
        monotonic=None,
    ):
        self.interval_seconds = _positive_seconds(interval_seconds)
        self.max_symbols = _positive_int(max_symbols)
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self._owns_http_client = http_client is None
        self.http_client = http_client or JsonHttpClient(
            sleep=self._wait_for_retry,
            check_cancelled=self._raise_if_stopped,
        )
        self.websocket_factory = websocket_factory or websocket.create_connection
        self.now_ms = now_ms or (lambda: int(time.time() * 1000))
        self.monotonic = monotonic or time.monotonic
        self.window = RollingCvdWindow(now_ms=self.now_ms())
        self.websocket_url = None
        self.connection = None
        self.next_refresh_at = 0.0
        self.error = None

    def refresh_universe(self):
        tickers = self.http_client.get_json(TICKER_URL, timeout=12, attempts=3)
        self._raise_if_stopped()
        exchange_info = self.http_client.get_json(
            EXCHANGE_INFO_URL, timeout=12, attempts=3
        )
        symbols = select_cvd_symbols(tickers, exchange_info, self.max_symbols)
        with self.lock:
            self.window.set_tracked_symbols(symbols, now_ms=self.now_ms())
            self.websocket_url = _combined_stream_url(symbols)
            self.next_refresh_at = self.monotonic() + self.interval_seconds
            self.error = None
        return symbols

    def handle_message(self, message):
        try:
            payload = json.loads(message)
            data = payload.get("data", payload)
            symbol = data["s"]
            event_ms = data["E"]
            price = data["p"]
            quantity = data["q"]
            buyer_is_maker = data["m"]
        except (TypeError, ValueError, KeyError):
            return False
        with self.lock:
            accepted = self.window.add_trade(
                symbol,
                event_ms,
                price=price,
                quantity=quantity,
                buyer_is_maker=buyer_is_maker,
            )
            if accepted:
                self.error = None
            return accepted

    def refresh_rest_fallback(self):
        """Rebuild the rolling CVD window from one-minute REST klines."""
        with self.lock:
            symbols = set(self.window.tracked_symbols)
        fallback_now_ms = self.now_ms()
        rebuilt_window = RollingCvdWindow(now_ms=fallback_now_ms)
        rebuilt_window.set_tracked_symbols(symbols, now_ms=fallback_now_ms)
        populated = False
        for symbol in symbols:
            try:
                klines = self.http_client.get_json(
                    KLINES_URL,
                    params={"symbol": symbol, "interval": "1m", "limit": 15},
                    timeout=12,
                    attempts=3,
                )
                if not _add_kline_cvd_events(rebuilt_window, symbol, klines):
                    continue
            except Exception:
                continue
            rebuilt_window.coverage_started_at[symbol] = (
                fallback_now_ms - rebuilt_window.coverage_ms
            )
            populated = True
        with self.lock:
            if populated:
                self.window = rebuilt_window
                self.error = None
            elif not any(self.window.events_by_symbol.values()):
                self.error = "CVD unavailable"
        return populated

    def get_state(self):
        with self.lock:
            return {
                "rows": self.window.snapshots(now_ms=self.now_ms()),
                "tracked_symbols": sorted(self.window.tracked_symbols),
                "error": self.error,
            }

    def run_forever(self):
        retry_delay = 1.0
        while not self.stop_event.is_set():
            try:
                self.refresh_universe()
                self._consume_stream()
                retry_delay = 1.0
            except Exception as exc:
                if self.stop_event.is_set():
                    break
                with self.lock:
                    self.error = str(exc)
                self.stop_event.wait(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)
            finally:
                self._close_connection()

    def _consume_stream(self):
        with self.lock:
            url = self.websocket_url
        if not url:
            return
        connection = self.websocket_factory(url, timeout=1)
        with self.lock:
            self.connection = connection
        while not self.stop_event.is_set():
            if self.monotonic() >= self.next_refresh_at:
                return
            try:
                message = connection.recv()
            except websocket.WebSocketTimeoutException:
                continue
            if message is None:
                raise ConnectionError("CVD WebSocket closed")
            self.handle_message(message)

    def stop(self):
        self.stop_event.set()
        self._close_connection()

    def close(self):
        self._close_connection()
        if self._owns_http_client:
            self.http_client.close()

    def _close_connection(self):
        with self.lock:
            connection, self.connection = self.connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass

    def _raise_if_stopped(self):
        if self.stop_event.is_set():
            raise RuntimeError("CVD polling stopped")

    def _wait_for_retry(self, delay):
        if self.stop_event.wait(delay):
            self._raise_if_stopped()


def _combined_stream_url(symbols):
    streams = "/".join(f"{symbol.lower()}@aggTrade" for symbol in sorted(symbols))
    return f"{STREAM_BASE_URL}{streams}"


def _add_kline_cvd_events(window, symbol, klines):
    if not isinstance(klines, list) or len(klines) != 15:
        return False
    events = []
    previous_event_ms = None
    for kline in klines:
        if not isinstance(kline, (list, tuple)) or len(kline) <= 10:
            return False
        try:
            event_ms = int(kline[6])
            quote_volume = float(kline[7])
            taker_buy_quote_volume = float(kline[10])
        except (TypeError, ValueError, OverflowError):
            return False
        if (
            event_ms < 0
            or not isfinite(quote_volume)
            or not isfinite(taker_buy_quote_volume)
            or quote_volume < 0
            or taker_buy_quote_volume < 0
            or taker_buy_quote_volume > quote_volume
            or (
                previous_event_ms is not None
                and event_ms < previous_event_ms
            )
        ):
            return False
        previous_event_ms = event_ms
        taker_sell_quote_volume = quote_volume - taker_buy_quote_volume
        if taker_buy_quote_volume:
            events.append((event_ms, taker_buy_quote_volume, False))
        if taker_sell_quote_volume:
            events.append((event_ms, taker_sell_quote_volume, True))
    for event_ms, quote_volume, buyer_is_maker in events:
        if not window.add_trade(
            symbol,
            event_ms,
            price=quote_volume,
            quantity=1,
            buyer_is_maker=buyer_is_maker,
        ):
            return False
    return True


def select_cvd_symbols(tickers, exchange_info, max_symbols):
    perpetuals = {
        item.get("symbol")
        for item in exchange_info.get("symbols", [])
        if isinstance(item, dict)
        and item.get("contractType") == "PERPETUAL"
        and item.get("status") == "TRADING"
    }
    candidates = []
    for ticker in tickers:
        if not isinstance(ticker, dict):
            continue
        symbol = ticker.get("symbol")
        if (
            not isinstance(symbol, str)
            or not symbol.endswith("USDT")
            or "_" in symbol
            or symbol not in perpetuals
        ):
            continue
        try:
            volume = float(ticker.get("quoteVolume", 0))
        except (TypeError, ValueError, OverflowError):
            continue
        if isfinite(volume) and volume > 0:
            candidates.append((volume, symbol))
    candidates.sort(reverse=True)
    return {symbol for _, symbol in candidates[:max_symbols]}


def _positive_seconds(value):
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("interval_seconds must be positive") from exc
    if parsed <= 0:
        raise ValueError("interval_seconds must be positive")
    return parsed


def _positive_int(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("max_symbols must be a positive integer")
    return value
