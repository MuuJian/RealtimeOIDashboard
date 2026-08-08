"""One independently reconnecting Binance kline WebSocket shard."""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict

import websocket


STREAM_URL = "wss://fstream.binance.com/market/stream"
SUBSCRIPTION_BATCH_SIZE = 100
CONTROL_MESSAGE_INTERVAL_SECONDS = 0.21
CONNECTION_ROTATE_SECONDS = 85_800


class BinanceCvdShard:
    def __init__(
        self,
        shard_id: int,
        on_kline,
        on_health,
        *,
        websocket_factory=None,
        monotonic=time.monotonic,
        wall_time=time.time,
        rotate_seconds=CONNECTION_ROTATE_SECONDS,
    ) -> None:
        self.shard_id = shard_id
        self._on_kline = on_kline
        self._on_health = on_health
        self._websocket_factory = websocket_factory or websocket.create_connection
        self._monotonic = monotonic
        self._wall_time = wall_time
        self._rotate_seconds = float(rotate_seconds)
        self._rotation_stagger_seconds = (shard_id % 60) * 60.0
        self._lock = threading.RLock()
        self._desired_symbols: set[str] = set()
        self._subscribed_symbols: set[str] = set()
        self._confirmed_symbols: set[str] = set()
        self._pending_controls: dict[int, tuple[str, set[str]]] = {}
        self._symbol_counts = defaultdict(int)
        self._connection = None
        self._thread = None
        self._stop_event = threading.Event()
        self._connected = False
        self._request_id = shard_id * 1_000_000
        self._message_count = 0
        self._rate_window_started = self._monotonic()
        self._messages_per_second = 0.0
        self._processing_lag_ms = 0.0
        self._connected_at = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run,
            name=f"cvd-shard-{self.shard_id}",
            daemon=True,
        )
        self._thread.start()

    def update_symbols(self, symbols: set[str]) -> None:
        with self._lock:
            self._desired_symbols = set(symbols)

    def stop(self, *, timeout=5.0) -> None:
        self.request_stop()
        self.wait_stopped(timeout=timeout)

    def request_stop(self) -> None:
        self._stop_event.set()
        self._close_connection()

    def wait_stopped(self, *, timeout=5.0) -> None:
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def metrics(self) -> dict:
        with self._lock:
            elapsed = max(self._monotonic() - self._rate_window_started, 0.001)
            current_rate = self._message_count / elapsed
            return {
                "shardId": self.shard_id,
                "symbolCount": len(self._desired_symbols),
                "connected": self._connected,
                "confirmedSymbols": len(self._confirmed_symbols),
                "messagesPerSecond": max(self._messages_per_second, current_rate),
                "processingLagMs": self._processing_lag_ms,
                "queueDepth": 0,
                "symbolRates": {
                    symbol: count / elapsed
                    for symbol, count in self._symbol_counts.items()
                },
            }

    def confirmed_symbols(self) -> set[str]:
        with self._lock:
            return set(self._confirmed_symbols)

    def _run(self) -> None:
        retry_delay = 1.0
        while not self._stop_event.is_set():
            try:
                self._connect()
                retry_delay = 1.0
                self._consume()
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                self._set_health(False, str(exc))
                self._stop_event.wait(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)
            finally:
                self._close_connection()

    def _connect(self) -> None:
        connection = self._websocket_factory(STREAM_URL, timeout=1)
        with self._lock:
            self._connection = connection
            self._subscribed_symbols = set()
            self._confirmed_symbols = set()
            self._pending_controls = {}
            self._connected_at = self._monotonic()
            self._connected = True
        self._sync_subscriptions()

    def _consume(self) -> None:
        while not self._stop_event.is_set():
            self._sync_subscriptions()
            with self._lock:
                connection = self._connection
                connected_at = self._connected_at
            if connection is None:
                return
            if (
                connected_at is not None
                and self._monotonic() - connected_at
                >= self._rotate_seconds + self._rotation_stagger_seconds
            ):
                try:
                    self._rotate_connection()
                except Exception:
                    # The original connection remains usable when a smooth
                    # replacement cannot be confirmed. Retry after one minute.
                    with self._lock:
                        self._connected_at = (
                            self._monotonic()
                            - self._rotate_seconds
                            - self._rotation_stagger_seconds
                            + 60.0
                        )
                continue
            try:
                message = connection.recv()
            except websocket.WebSocketTimeoutException:
                self._roll_rate_window()
                continue
            if message is None:
                raise ConnectionError("CVD WebSocket closed")
            self._handle_message(message)

    def _sync_subscriptions(self) -> None:
        with self._lock:
            desired = set(self._desired_symbols)
            subscribed = set(self._subscribed_symbols)
        self._send_control("SUBSCRIBE", desired - subscribed)
        self._send_control("UNSUBSCRIBE", subscribed - desired)

    def _send_control(self, method: str, symbols: set[str]) -> None:
        ordered = sorted(symbols)
        for offset in range(0, len(ordered), SUBSCRIPTION_BATCH_SIZE):
            if self._stop_event.is_set():
                return
            batch = ordered[offset:offset + SUBSCRIPTION_BATCH_SIZE]
            with self._lock:
                connection = self._connection
                self._request_id += 1
                request_id = self._request_id
            if connection is None:
                return
            connection.send(json.dumps({
                "method": method,
                "params": [f"{symbol.lower()}@kline_1m" for symbol in batch],
                "id": request_id,
            }))
            with self._lock:
                self._pending_controls[request_id] = (method, set(batch))
                if method == "SUBSCRIBE":
                    self._subscribed_symbols.update(batch)
                else:
                    self._subscribed_symbols.difference_update(batch)
                    self._confirmed_symbols.difference_update(batch)
            if offset + SUBSCRIPTION_BATCH_SIZE < len(ordered):
                self._stop_event.wait(CONTROL_MESSAGE_INTERVAL_SECONDS)

    def _rotate_connection(self) -> None:
        replacement = self._websocket_factory(STREAM_URL, timeout=1)
        with self._lock:
            desired = set(self._desired_symbols)
            old_connection = self._connection
        try:
            ordered = sorted(desired)
            pending_request_ids = set()
            for offset in range(0, len(ordered), SUBSCRIPTION_BATCH_SIZE):
                batch = ordered[offset:offset + SUBSCRIPTION_BATCH_SIZE]
                with self._lock:
                    self._request_id += 1
                    request_id = self._request_id
                replacement.send(json.dumps({
                    "method": "SUBSCRIBE",
                    "params": [
                        f"{symbol.lower()}@kline_1m" for symbol in batch
                    ],
                    "id": request_id,
                }))
                pending_request_ids.add(request_id)
                if offset + SUBSCRIPTION_BATCH_SIZE < len(ordered):
                    self._stop_event.wait(CONTROL_MESSAGE_INTERVAL_SECONDS)

            # Keep the old socket open until every subscription batch is
            # acknowledged and the replacement starts delivering real data.
            ready = not desired
            received_data = False
            deadline = self._monotonic() + 10.0
            while not ready and self._monotonic() < deadline:
                try:
                    message = replacement.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if message is None:
                    break
                try:
                    payload = json.loads(message)
                    if payload.get("result") is None and "id" in payload:
                        pending_request_ids.discard(payload["id"])
                    data = payload.get("data", payload)
                    if isinstance(data, dict) and isinstance(data.get("k"), dict):
                        received_data = True
                        self._handle_message(message)
                    ready = received_data and not pending_request_ids
                except (AttributeError, TypeError, ValueError):
                    ready = False
            if not ready:
                raise ConnectionError("replacement CVD shard was not confirmed")

            with self._lock:
                if self._connection is not old_connection:
                    return
                self._connection = replacement
                self._subscribed_symbols = desired
                self._confirmed_symbols = set(desired)
                self._pending_controls = {}
                self._connected_at = self._monotonic()
            replacement = None
            if old_connection is not None:
                old_connection.close()
        finally:
            if replacement is not None:
                try:
                    replacement.close()
                except Exception:
                    pass

    def _handle_message(self, message) -> None:
        received_at = self._monotonic()
        try:
            payload = json.loads(message)
            if "id" in payload:
                if payload.get("result") is not None or "code" in payload:
                    raise ConnectionError(
                        f"CVD subscription rejected: {payload.get('msg', payload)}"
                    )
                notify_symbols = set()
                with self._lock:
                    control = self._pending_controls.pop(payload["id"], None)
                    if control is not None:
                        method, symbols = control
                        if method == "SUBSCRIBE":
                            self._confirmed_symbols.update(
                                symbols.intersection(self._desired_symbols)
                            )
                            if self._desired_symbols.issubset(
                                self._confirmed_symbols
                            ):
                                notify_symbols = set(self._desired_symbols)
                        else:
                            self._confirmed_symbols.difference_update(symbols)
                if notify_symbols:
                    self._on_health(
                        self.shard_id,
                        notify_symbols,
                        True,
                        None,
                    )
                return
            data = payload.get("data", payload)
            kline = data["k"]
            symbol = kline["s"]
            event_ms = int(data.get("E", int(self._wall_time() * 1000)))
            values = {
                "open_time": int(kline["t"]),
                "quote_volume": kline["q"],
                "taker_buy_quote_volume": kline["Q"],
                "closed": bool(kline["x"]),
                "source": "wss",
                "updated_at": event_ms,
            }
        except (KeyError, TypeError, ValueError, OverflowError):
            return
        with self._lock:
            if symbol not in self._desired_symbols:
                return
            self._confirmed_symbols.add(symbol)
            self._message_count += 1
            self._symbol_counts[symbol] += 1
            wall_lag = max(int(self._wall_time() * 1000) - event_ms, 0)
            processing_ms = (self._monotonic() - received_at) * 1000
            self._processing_lag_ms = max(wall_lag, processing_ms)
        self._on_kline(self.shard_id, symbol, values)
        self._roll_rate_window()

    def _roll_rate_window(self) -> None:
        now = self._monotonic()
        with self._lock:
            elapsed = now - self._rate_window_started
            if elapsed < 5.0:
                return
            sample = self._message_count / max(elapsed, 0.001)
            self._messages_per_second = (
                sample
                if self._messages_per_second == 0
                else self._messages_per_second * 0.7 + sample * 0.3
            )
            self._message_count = 0
            self._symbol_counts.clear()
            self._rate_window_started = now

    def _set_health(self, connected: bool, reason: str | None) -> None:
        with self._lock:
            self._connected = connected
            symbols = set(self._desired_symbols)
        self._on_health(self.shard_id, symbols, connected, reason)

    def _close_connection(self) -> None:
        with self._lock:
            connection, self._connection = self._connection, None
            was_connected = self._connected
            self._connected = False
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
        if was_connected and not self._stop_event.is_set():
            self._on_health(
                self.shard_id,
                set(self._desired_symbols),
                False,
                "CVD shard disconnected",
            )
