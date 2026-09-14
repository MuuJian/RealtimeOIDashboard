"""Enforce bounded rolling Binance REST weight and history-request budgets."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from math import isfinite
from urllib.parse import parse_qs, urlparse


DEFAULT_WEIGHT_PER_MINUTE = 1_800.0
INVALID_CAPACITY_ERROR = "weight_per_minute must be a finite positive number"
BINANCE_HOSTS = {"fapi.binance.com", "testnet.binancefuture.com", "demo-fapi.binance.com"}
HISTORY_REQUESTS_PER_FIVE_MINUTES = 1000


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
        self._weights = deque()
        self._used_weight = 0.0
        self._history_requests = deque()
        self._blocked_until = 0.0
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()

    def acquire(
        self,
        url: str,
        *,
        params=None,
        check_cancelled: Callable[[], None] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        weight = request_weight(url, params=params)
        parsed = urlparse(url)
        history = (
            parsed.hostname in BINANCE_HOSTS
            and parsed.path.endswith("/openInterestHist")
        )
        if weight <= 0 and not history:
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
                while self._weights and self._weights[0][0] <= now - 60:
                    self._used_weight -= self._weights.popleft()[1]
                while self._history_requests and self._history_requests[0] <= now - 300:
                    self._history_requests.popleft()
                waits = []
                if now < self._blocked_until:
                    waits.append(self._blocked_until - now)
                if self._used_weight + weight > self._capacity:
                    waits.append(self._weights[0][0] + 60 - now)
                if history and len(self._history_requests) >= HISTORY_REQUESTS_PER_FIVE_MINUTES:
                    waits.append(self._history_requests[0] + 300 - now)
                if not waits:
                    if weight > 0:
                        self._weights.append((now, weight))
                        self._used_weight += weight
                    if history:
                        self._history_requests.append(now)
                    return
                wait_for = max(waits)
            if check_cancelled is not None:
                check_cancelled()
            wait(min(wait_for, 1.0))

    def defer(self, url: str, seconds: float) -> None:
        if urlparse(url).hostname not in BINANCE_HOSTS:
            return
        if not isfinite(seconds) or seconds <= 0:
            return
        with self._lock:
            self._blocked_until = max(self._blocked_until, self._monotonic() + seconds)


def request_weight(url: str, *, params=None) -> float:
    try:
        parsed = urlparse(url)
    except (TypeError, ValueError):
        return 0.0
    if parsed.hostname not in BINANCE_HOSTS:
        return 0.0
    path = parsed.path
    query = {key: value[-1] for key, value in parse_qs(parsed.query).items()}
    query.update(params or {})
    if path.endswith("/openInterestHist"):
        return 0.0
    if path.endswith("/klines"):
        try:
            limit = int(query.get("limit", 500))
        except (TypeError, ValueError, OverflowError):
            return 10.0
        return 1.0 if limit < 100 else 2.0 if limit < 500 else 5.0 if limit <= 1000 else 10.0
    if path.endswith("/ticker/24hr"):
        return 1.0 if query.get("symbol") else 40.0
    if path.endswith("/premiumIndex"):
        return 1.0 if query.get("symbol") else 10.0
    return 1.0


GLOBAL_BINANCE_WEIGHT_BUDGET = BinanceWeightBudget()
