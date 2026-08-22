"""Enforce a process-wide soft Binance REST weight budget."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from math import isfinite
from urllib.parse import urlparse


DEFAULT_WEIGHT_PER_MINUTE = 1_800.0
INVALID_CAPACITY_ERROR = (
    "weight_per_minute must be a finite positive number"
)


class BinanceWeightBudget:
    def __init__(
        self,
        *,
        weight_per_minute=DEFAULT_WEIGHT_PER_MINUTE,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        if isinstance(weight_per_minute, bool):
            raise ValueError(INVALID_CAPACITY_ERROR)
        try:
            capacity = float(weight_per_minute)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(INVALID_CAPACITY_ERROR) from exc
        if not isfinite(capacity) or capacity <= 0:
            raise ValueError(INVALID_CAPACITY_ERROR)

        self._capacity = capacity
        self._refill_per_second = self._capacity / 60.0
        self._tokens = self._capacity
        self._monotonic = monotonic
        self._sleep = sleep
        self._updated_at = monotonic()
        self._lock = threading.Lock()

    def acquire(
        self,
        url: str,
        *,
        check_cancelled: Callable[[], None] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        weight = request_weight(url)
        if weight <= 0:
            return
        if weight > self._capacity:
            raise ValueError(
                f"request weight {weight:g} exceeds budget capacity "
                f"{self._capacity:g}"
            )
        wait = self._sleep if sleep is None else sleep
        while True:
            if check_cancelled is not None:
                check_cancelled()
            with self._lock:
                now = self._monotonic()
                elapsed = max(now - self._updated_at, 0.0)
                self._tokens = min(
                    self._capacity,
                    self._tokens + elapsed * self._refill_per_second,
                )
                self._updated_at = now
                if self._tokens >= weight:
                    self._tokens -= weight
                    return
                wait_for = (weight - self._tokens) / self._refill_per_second
            if check_cancelled is not None:
                check_cancelled()
            wait(min(wait_for, 1.0))


def request_weight(url: str) -> float:
    try:
        parsed = urlparse(url)
    except (TypeError, ValueError):
        return 0.0
    if parsed.hostname not in {"fapi.binance.com", "testnet.binancefuture.com"}:
        return 0.0
    path = parsed.path
    if path.endswith("/ticker/24hr"):
        return 40.0
    if path.endswith("/premiumIndex"):
        return 10.0
    return 1.0


GLOBAL_BINANCE_WEIGHT_BUDGET = BinanceWeightBudget()
