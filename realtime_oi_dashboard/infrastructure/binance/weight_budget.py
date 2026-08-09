"""Enforce a process-wide soft Binance REST weight budget."""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse


DEFAULT_WEIGHT_PER_MINUTE = 1_800.0


class BinanceWeightBudget:
    def __init__(
        self,
        *,
        weight_per_minute=DEFAULT_WEIGHT_PER_MINUTE,
        monotonic=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self._capacity = float(weight_per_minute)
        self._refill_per_second = self._capacity / 60.0
        self._tokens = self._capacity
        self._monotonic = monotonic
        self._sleep = sleep
        self._updated_at = monotonic()
        self._lock = threading.Lock()

    def acquire(self, url: str) -> None:
        weight = request_weight(url)
        if weight <= 0:
            return
        while True:
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
            self._sleep(min(wait_for, 1.0))


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
