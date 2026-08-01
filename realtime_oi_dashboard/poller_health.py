"""Thread-safe recent errors and clock health for the OI poller."""

from __future__ import annotations

import threading
import time
from collections import deque
from math import isfinite


class RecentErrorLog:
    def __init__(self, stop_event, *, max_events=10, retention_seconds=60) -> None:
        self._stop_event = stop_event
        self._retention_seconds = retention_seconds
        self._lock = threading.Lock()
        self._events = deque(maxlen=max_events)

    def record(self, symbol: str, error: Exception) -> bool:
        if self._stop_event.is_set():
            return False
        with self._lock:
            if self._stop_event.is_set():
                return False
            self._events.append(
                {
                    "symbol": symbol,
                    "error": str(error),
                    "recorded_at": time.monotonic(),
                }
            )
        return True

    def recent(self) -> list[dict[str, str]]:
        with self._lock:
            cutoff = time.monotonic() - self._retention_seconds
            while self._events and self._events[0]["recorded_at"] < cutoff:
                self._events.popleft()
            return [
                {"symbol": item["symbol"], "error": item["error"]}
                for item in self._events
            ]

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class PollerClock:
    def __init__(
        self,
        *,
        row_max_age_seconds: float,
        clock_skew_seconds: float,
        discontinuity_tolerance_seconds: float,
    ) -> None:
        self._row_max_age_seconds = row_max_age_seconds
        self._clock_skew_seconds = clock_skew_seconds
        self._discontinuity_tolerance_seconds = discontinuity_tolerance_seconds
        self._last_success_wall_clock = None
        self._last_wall_clock = time.time()
        self._last_monotonic_clock = time.monotonic()

    def observe_discontinuity(
        self,
        *,
        wall_now: float | None = None,
        monotonic_now: float | None = None,
    ) -> bool:
        current_wall = time.time() if wall_now is None else wall_now
        current_monotonic = (
            time.monotonic() if monotonic_now is None else monotonic_now
        )
        wall_elapsed = current_wall - self._last_wall_clock
        monotonic_elapsed = current_monotonic - self._last_monotonic_clock
        self._last_wall_clock = current_wall
        self._last_monotonic_clock = current_monotonic
        return (
            abs(wall_elapsed - monotonic_elapsed)
            > self._discontinuity_tolerance_seconds
        )

    def mark_success(self, wall_now: float) -> None:
        self._last_success_wall_clock = wall_now

    def clear_success(self) -> None:
        self._last_success_wall_clock = None

    def rows_are_stale(self, wall_now: float) -> bool:
        if self._last_success_wall_clock is None:
            return True
        age = wall_now - self._last_success_wall_clock
        return (
            not isfinite(age)
            or age < -self._clock_skew_seconds
            or age > self._row_max_age_seconds
        )
