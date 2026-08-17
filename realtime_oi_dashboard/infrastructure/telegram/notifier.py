"""Bounded asynchronous Telegram alert delivery."""

from __future__ import annotations

import os
import queue
import threading
import time
from datetime import datetime, timezone
from urllib.request import Request, urlopen
import json

from realtime_oi_dashboard.domain.oi_alerts.model import AlertEvent


_UNSET = object()
_STOP_WAIT_SECONDS = 0.1
_RETRY_DELAYS = (1, 2, 4)
_DELIVERY_FAILED = "Telegram delivery failed"
_QUEUE_FULL = "delivery queue is full"


class TelegramNotifier:
    """Deliver alert messages without blocking the OI polling thread."""

    def __init__(
        self,
        bot_token=_UNSET,
        chat_id=_UNSET,
        *,
        post_json=None,
        mark_delivery=None,
        sleep=time.sleep,
    ) -> None:
        self._bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") if bot_token is _UNSET else bot_token
        self._chat_id = os.environ.get("TELEGRAM_CHAT_ID") if chat_id is _UNSET else chat_id
        self._post_json = post_json or _post_json
        self._mark_delivery = mark_delivery or (lambda event, status, error: None)
        self._sleep = sleep
        self._queue = queue.Queue(maxsize=100)
        self._stop_event = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._status = "configured" if self.is_configured else "not_configured"
        self._last_error = None
        self._last_attempt_at = None

    @property
    def is_configured(self) -> bool:
        return bool(self._bot_token and self._chat_id)

    def start(self) -> None:
        if not self.is_configured:
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def stop(self, timeout) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def enqueue(self, event: AlertEvent) -> None:
        if not self.is_configured:
            self._report(event, "not_configured", None)
            return
        self.start()
        try:
            self._queue.put_nowait((event, _event_message(event)))
        except queue.Full:
            with self._lock:
                self._status = "failed"
                self._last_error = _QUEUE_FULL
            self._report(event, "failed", _QUEUE_FULL)

    def send_test_message(self) -> bool:
        if not self.is_configured:
            return False
        self.start()
        try:
            self._queue.put_nowait((None, "OI Alerts Telegram test message"))
        except queue.Full:
            with self._lock:
                self._status = "failed"
                self._last_error = _QUEUE_FULL
            return False
        return True

    def get_status(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "last_error": self._last_error,
                "last_attempt_at": self._last_attempt_at,
            }

    def drain_for_test(self) -> None:
        self._queue.join()

    def _run(self) -> None:
        while not self._stop_event.is_set() or not self._queue.empty():
            try:
                event, text = self._queue.get(timeout=_STOP_WAIT_SECONDS)
            except queue.Empty:
                continue
            try:
                self._deliver(event, text)
            finally:
                self._queue.task_done()

    def _deliver(self, event: AlertEvent | None, text: str) -> None:
        error = None
        for attempt in range(3):
            try:
                self._record_attempt()
                self._post_json(self._endpoint(), {"chat_id": self._chat_id, "text": text})
            except Exception:
                error = _DELIVERY_FAILED
                if attempt < 2:
                    self._sleep(_RETRY_DELAYS[attempt])
                continue
            self._mark_success(event)
            return
        self._mark_failure(event, error)

    def _endpoint(self) -> str:
        return f"https://api.telegram.org/bot{self._bot_token}/sendMessage"

    def _record_attempt(self) -> None:
        with self._lock:
            self._status = "sending"
            self._last_attempt_at = datetime.now(timezone.utc).isoformat()

    def _mark_success(self, event: AlertEvent | None) -> None:
        with self._lock:
            self._status = "configured"
            self._last_error = None
        if event is not None:
            self._report(event, "sent", None)

    def _mark_failure(self, event: AlertEvent | None, error: str | None) -> None:
        with self._lock:
            self._status = "failed"
            self._last_error = error
        if event is not None:
            self._report(event, "failed", error)

    def _report(self, event: AlertEvent, status: str, error: str | None) -> None:
        try:
            self._mark_delivery(event, status, error)
        except Exception:
            pass


def _event_message(event: AlertEvent) -> str:
    return (
        f"OI alert: {event.symbol} crossed ${event.threshold:,.0f} "
        f"({event.signal}); current OI ${event.oi_value:,.0f}."
    )


def _post_json(url: str, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=10):
        pass
