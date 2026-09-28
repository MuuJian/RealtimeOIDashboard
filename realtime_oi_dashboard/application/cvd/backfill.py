"""Repair missing CVD minutes with a bounded REST queue."""

from __future__ import annotations

import random
import threading
import time
from collections import deque

from realtime_oi_dashboard.infrastructure.binance.weight_budget import BinanceCooldownError
from realtime_oi_dashboard.infrastructure.http import _retry_after_seconds


BACKFILL_REQUESTS_PER_SECOND = 4.0
BACKFILL_WORKERS = 2
MAX_RETRIES = 5
MAX_PENDING_TASKS = 10_000


class _RequestPacer:
    def __init__(self, requests_per_second, *, monotonic=time.monotonic) -> None:
        self._interval = 1.0 / float(requests_per_second)
        self._monotonic = monotonic
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self, stop_event) -> bool:
        with self._lock:
            now = self._monotonic()
            wait_for = max(self._next_at - now, 0.0)
            self._next_at = max(now, self._next_at) + self._interval
        return stop_event.wait(wait_for)


class CvdBackfillQueue:
    def __init__(
        self,
        load_symbol,
        apply_rows,
        *,
        requests_per_second=BACKFILL_REQUESTS_PER_SECOND,
        workers=BACKFILL_WORKERS,
        monotonic=time.monotonic,
        random_value=random.random,
        max_pending=MAX_PENDING_TASKS,
    ) -> None:
        self._load_symbol = load_symbol
        self._apply_rows = apply_rows
        self._worker_count = int(workers)
        self._pacer = _RequestPacer(
            requests_per_second,
            monotonic=monotonic,
        )
        self._random_value = random_value
        self._max_pending = int(max_pending)
        self._condition = threading.Condition()
        self._pending = deque()
        self._queued = set()
        self._inflight = set()
        self._threads = []
        self._stop_event = threading.Event()
        self._started = False
        self._monotonic = monotonic
        self._blocked_until = 0.0
        self.last_error: str | None = None

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        for index in range(self._worker_count):
            thread = threading.Thread(
                target=self._run_worker,
                name=f"cvd-backfill-{index}",
                daemon=True,
            )
            self._threads.append(thread)
            thread.start()

    def enqueue(self, symbol: str) -> bool:
        with self._condition:
            if (
                self._stop_event.is_set()
                or symbol in self._queued
                or symbol in self._inflight
                or len(self._queued) + len(self._inflight) >= self._max_pending
            ):
                return False
            self._queued.add(symbol)
            self._pending.append((symbol, 0))
            self._condition.notify()
            return True

    def stop(self, *, timeout=5.0) -> None:
        self._stop_event.set()
        with self._condition:
            self._condition.notify_all()
        deadline = time.monotonic() + timeout
        for thread in self._threads:
            thread.join(timeout=max(deadline - time.monotonic(), 0.0))

    @property
    def queue_size(self) -> int:
        with self._condition:
            return len(self._pending) + len(self._inflight)

    def _run_worker(self) -> None:
        while not self._stop_event.is_set():
            task = self._take()
            if task is None:
                continue
            symbol, attempt = task
            retry = False
            count_attempt = True
            try:
                if self._pacer.wait(self._stop_event):
                    return
                with self._condition:
                    while self._blocked_until > self._monotonic():
                        if self._stop_event.is_set():
                            return
                        self._condition.wait(timeout=min(self._blocked_until - self._monotonic(), 1))
                rows = self._load_symbol(symbol)
                if self._stop_event.is_set():
                    return
                self._apply_rows(symbol, rows)
                self.last_error = None
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                self.last_error = str(exc)
                if isinstance(exc, BinanceCooldownError):
                    self._block(exc)
                    retry = True
                    # An IP-wide cooldown is not a failed symbol repair. Keep
                    # the work queued until requests are permitted again.
                    count_attempt = False
                elif status in (418, 429):
                    self._block(exc)
                    retry = attempt + 1 < MAX_RETRIES
                elif attempt + 1 < MAX_RETRIES:
                    delay = _retry_delay(
                        exc,
                        attempt,
                        random_value=self._random_value,
                    )
                    if not self._stop_event.wait(delay):
                        retry = True
            finally:
                self._finish(symbol, attempt, retry, count_attempt=count_attempt)

    def _take(self):
        with self._condition:
            while (
                (not self._pending or self._blocked_until > self._monotonic())
                and not self._stop_event.is_set()
            ):
                self._condition.wait(timeout=1)
            if self._stop_event.is_set() or not self._pending:
                return None
            symbol, attempt = self._pending.popleft()
            self._queued.discard(symbol)
            self._inflight.add(symbol)
            return symbol, attempt

    def _finish(
        self, symbol: str, attempt: int, retry: bool, *, count_attempt=True
    ) -> None:
        with self._condition:
            self._inflight.discard(symbol)
            if retry and not self._stop_event.is_set():
                self._queued.add(symbol)
                self._pending.append((symbol, attempt + int(count_attempt)))
                self._condition.notify()

    def _block(self, error) -> None:
        if isinstance(error, BinanceCooldownError):
            delay = max(error.retry_after, 0.01)
        else:
            response = getattr(error, "response", None)
            retry_after = getattr(response, "headers", {}).get("Retry-After", "")
            minimum = 120 if getattr(response, "status_code", None) == 418 else 10
            delay = max(_retry_after_seconds(retry_after) or 0, minimum)
        with self._condition:
            self._blocked_until = max(self._blocked_until, self._monotonic() + delay)
            self._condition.notify_all()


def _retry_delay(error, attempt: int, *, random_value) -> float:
    response = getattr(error, "response", None)
    if getattr(response, "status_code", None) == 429:
        retry_after = getattr(response, "headers", {}).get("Retry-After")
        try:
            parsed = float(retry_after)
        except (TypeError, ValueError, OverflowError):
            parsed = 10.0
        return max(parsed, 0.0)
    return min(2**attempt, 30) + random_value()
