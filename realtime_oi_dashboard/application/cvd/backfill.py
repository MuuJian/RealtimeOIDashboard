"""Repair missing CVD minutes with a bounded REST queue."""

from __future__ import annotations

import random
import threading
import time
from collections import deque


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
        self._blocked = False
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
                or self._blocked
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
            try:
                with self._condition:
                    if self._blocked:
                        continue
                if self._pacer.wait(self._stop_event):
                    return
                rows = self._load_symbol(symbol)
                if self._stop_event.is_set():
                    return
                self._apply_rows(symbol, rows)
                self.last_error = None
            except Exception as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                self.last_error = str(exc)
                if status == 418:
                    self._block()
                elif attempt + 1 < MAX_RETRIES:
                    delay = _retry_delay(
                        exc,
                        attempt,
                        random_value=self._random_value,
                    )
                    if not self._stop_event.wait(delay):
                        retry = True
            finally:
                self._finish(symbol, attempt, retry)

    def _take(self):
        with self._condition:
            while (
                (not self._pending or self._blocked)
                and not self._stop_event.is_set()
            ):
                self._condition.wait(timeout=1)
            if self._stop_event.is_set() or not self._pending:
                return None
            symbol, attempt = self._pending.popleft()
            self._queued.discard(symbol)
            self._inflight.add(symbol)
            return symbol, attempt

    def _finish(self, symbol: str, attempt: int, retry: bool) -> None:
        with self._condition:
            self._inflight.discard(symbol)
            if retry and not self._stop_event.is_set() and not self._blocked:
                self._queued.add(symbol)
                self._pending.append((symbol, attempt + 1))
                self._condition.notify()

    def _block(self) -> None:
        with self._condition:
            self._blocked = True
            self._pending.clear()
            self._queued.clear()
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
