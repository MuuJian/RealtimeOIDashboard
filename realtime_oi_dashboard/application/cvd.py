"""Background Binance aggregated-trade polling for CVD snapshots."""

from __future__ import annotations

import json
import threading
import time

import websocket

from realtime_oi_dashboard.domain.cvd import RollingCvdWindow
from realtime_oi_dashboard.domain.signal_scan import build_scan_universe
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient


FAPI_BASE_URL = "https://fapi.binance.com"
TICKER_URL = f"{FAPI_BASE_URL}/fapi/v1/ticker/24hr"
EXCHANGE_INFO_URL = f"{FAPI_BASE_URL}/fapi/v1/exchangeInfo"
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
        scan_pool, _ = build_scan_universe(tickers, exchange_info)
        symbols = {ticker["symbol"] for ticker in scan_pool[: self.max_symbols]}
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
