"""Fixed-memory minute-bucket CVD calculations."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from math import isfinite


MINUTE_MS = 60_000
WINDOW_MINUTES = 15
BUCKET_COUNT = WINDOW_MINUTES + 1
STATUS_THRESHOLD = 0.10


class CvdDirection(str, Enum):
    BUYING = "buying"
    SELLING = "selling"
    NEUTRAL = "neutral"


class CvdHealth(str, Enum):
    WARMING = "warming"
    LIVE = "live"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MinuteBucket:
    open_time: int
    quote_volume: float
    taker_buy_quote_volume: float
    delta: float
    total: float
    closed: bool
    source: str
    updated_at: int

    def to_json(self) -> dict:
        return {
            "openTime": self.open_time,
            "quoteVolume": self.quote_volume,
            "takerBuyQuoteVolume": self.taker_buy_quote_volume,
            "closed": self.closed,
        }


class SymbolCvdWindow:
    """Store 16 minute buckets and update cumulative values in O(1)."""

    def __init__(self, symbol: str) -> None:
        if not _is_symbol(symbol):
            raise ValueError("symbol must be an uppercase Binance symbol")
        self.symbol = symbol
        self._buckets: list[MinuteBucket | None] = [None] * BUCKET_COUNT
        self._lock = threading.Lock()
        self._rolling_delta = 0.0
        self._rolling_total = 0.0
        self._latest_open_time: int | None = None
        self._as_of: int | None = None
        self._connected = False
        self._reason: str | None = "waiting for first CVD data"

    def update(
        self,
        *,
        open_time,
        quote_volume,
        taker_buy_quote_volume,
        closed,
        source,
        updated_at,
    ) -> bool:
        bucket = _minute_bucket(
            open_time=open_time,
            quote_volume=quote_volume,
            taker_buy_quote_volume=taker_buy_quote_volume,
            closed=closed,
            source=source,
            updated_at=updated_at,
        )
        if bucket is None:
            return False

        with self._lock:
            index = _bucket_index(bucket.open_time)
            previous = self._buckets[index]
            if (
                previous is not None
                and previous.open_time == bucket.open_time
                and previous.updated_at > bucket.updated_at
            ):
                return False

            if previous is not None:
                self._rolling_delta -= previous.delta
                self._rolling_total -= previous.total
            self._buckets[index] = bucket
            self._rolling_delta += bucket.delta
            self._rolling_total += bucket.total
            self._latest_open_time = max(
                bucket.open_time,
                self._latest_open_time or bucket.open_time,
            )
            self._as_of = max(bucket.updated_at, self._as_of or bucket.updated_at)
            self._reason = None
            self._prune_locked(self._latest_open_time)
            return True

    def ensure_zero(self, open_time: int, *, updated_at: int) -> bool:
        open_time = _aligned_minute(open_time)
        with self._lock:
            existing = self._buckets[_bucket_index(open_time)]
            if existing is not None and existing.open_time == open_time:
                return False
        return self.update(
            open_time=open_time,
            quote_volume=0.0,
            taker_buy_quote_volume=0.0,
            closed=True,
            source="synthetic",
            updated_at=updated_at,
        )

    def set_connected(self, connected: bool, reason: str | None = None) -> None:
        with self._lock:
            self._connected = bool(connected)
            if reason is not None or not connected:
                self._reason = reason or "CVD shard disconnected"

    def mark_partial(self, reason: str) -> None:
        with self._lock:
            self._reason = reason

    def snapshot(self, *, now_ms: int) -> dict:
        now_ms = _timestamp_ms(now_ms)
        current_open = _aligned_minute(now_ms)
        expected = [
            current_open - offset * MINUTE_MS
            for offset in range(WINDOW_MINUTES)
        ]
        with self._lock:
            buckets_by_open = {
                bucket.open_time: bucket
                for bucket in self._buckets
                if bucket is not None and bucket.open_time in expected
            }
            implicit_current = self._connected and current_open not in buckets_by_open
            covered_opens = set(buckets_by_open)
            if implicit_current:
                covered_opens.add(current_open)
            delta = sum(bucket.delta for bucket in buckets_by_open.values())
            total = sum(bucket.total for bucket in buckets_by_open.values())
            ratio = delta / total if total else 0.0
            coverage_minutes = _coverage_minutes(expected, covered_opens)
            observed_count = len(buckets_by_open) + int(implicit_current)
            health = self._health_locked(coverage_minutes, observed_count)
            direction = _direction_for(ratio)
            as_of = self._as_of or (now_ms if self._connected else None)
            reason = self._reason_for_locked(health, observed_count)

        if health == CvdHealth.UNAVAILABLE:
            return {
                "cvd15m": None,
                "cvd15mRatio": None,
                "cvdDirection": None,
                "cvdHealth": health.value,
                "cvdAsOf": as_of,
                "cvdCoverageSeconds": 0,
                "cvdReason": reason,
                "cvdStatus": "unavailable",
                "cvdUpdatedAt": as_of,
            }
        return {
            "cvd15m": delta,
            "cvd15mRatio": ratio,
            "cvdDirection": direction.value,
            "cvdHealth": health.value,
            "cvdAsOf": as_of,
            "cvdCoverageSeconds": coverage_minutes * 60,
            "cvdReason": reason,
            "cvdStatus": (
                "collecting"
                if health == CvdHealth.WARMING
                else direction.value
            ),
            "cvdUpdatedAt": as_of,
        }

    def export_buckets(self, *, cutoff_ms: int) -> list[dict]:
        with self._lock:
            return [
                bucket.to_json()
                for bucket in sorted(
                    (
                        item
                        for item in self._buckets
                        if item is not None and item.open_time >= cutoff_ms
                    ),
                    key=lambda item: item.open_time,
                )
            ]

    def has_open_time(self, open_time: int) -> bool:
        open_time = _aligned_minute(open_time)
        with self._lock:
            bucket = self._buckets[_bucket_index(open_time)]
            return bucket is not None and bucket.open_time == open_time

    def _prune_locked(self, reference_open: int) -> None:
        cutoff = reference_open - (BUCKET_COUNT - 1) * MINUTE_MS
        for index, bucket in enumerate(self._buckets):
            if bucket is None or bucket.open_time >= cutoff:
                continue
            self._rolling_delta -= bucket.delta
            self._rolling_total -= bucket.total
            self._buckets[index] = None

    def _health_locked(
        self,
        coverage_minutes: int,
        bucket_count: int,
    ) -> CvdHealth:
        if bucket_count == 0:
            return CvdHealth.UNAVAILABLE
        if not self._connected:
            return CvdHealth.STALE
        if coverage_minutes < WINDOW_MINUTES:
            if self._reason and "missing" in self._reason.lower():
                return CvdHealth.PARTIAL
            return CvdHealth.WARMING
        if bucket_count < WINDOW_MINUTES:
            return CvdHealth.PARTIAL
        return CvdHealth.LIVE

    def _reason_for_locked(self, health: CvdHealth, bucket_count: int):
        if health == CvdHealth.LIVE:
            return None
        if health == CvdHealth.WARMING:
            return f"warming: {bucket_count}/{WINDOW_MINUTES} minute buckets"
        return self._reason


def _minute_bucket(**values) -> MinuteBucket | None:
    try:
        open_time = _timestamp_ms(values["open_time"])
        quote_volume = float(values["quote_volume"])
        taker_buy = float(values["taker_buy_quote_volume"])
        updated_at = _timestamp_ms(values["updated_at"])
    except (TypeError, ValueError, OverflowError):
        return None
    if (
        open_time % MINUTE_MS != 0
        or not isfinite(quote_volume)
        or not isfinite(taker_buy)
        or quote_volume < 0
        or taker_buy < 0
        or taker_buy > quote_volume
        or not isinstance(values["closed"], bool)
        or values["source"] not in {"wss", "rest", "snapshot", "synthetic"}
    ):
        return None
    return MinuteBucket(
        open_time=open_time,
        quote_volume=quote_volume,
        taker_buy_quote_volume=taker_buy,
        delta=2 * taker_buy - quote_volume,
        total=quote_volume,
        closed=values["closed"],
        source=values["source"],
        updated_at=updated_at,
    )


def _coverage_minutes(expected, buckets_by_open) -> int:
    coverage = 0
    for open_time in expected:
        if open_time not in buckets_by_open:
            break
        coverage += 1
    return coverage


def _direction_for(ratio: float) -> CvdDirection:
    if ratio >= STATUS_THRESHOLD:
        return CvdDirection.BUYING
    if ratio <= -STATUS_THRESHOLD:
        return CvdDirection.SELLING
    return CvdDirection.NEUTRAL


def _bucket_index(open_time: int) -> int:
    return (open_time // MINUTE_MS) % BUCKET_COUNT


def _aligned_minute(value) -> int:
    return _timestamp_ms(value) // MINUTE_MS * MINUTE_MS


def _timestamp_ms(value) -> int:
    if isinstance(value, bool):
        raise ValueError("timestamp must be a non-negative integer")
    parsed = int(value)
    if parsed < 0:
        raise ValueError("timestamp must be a non-negative integer")
    return parsed


def _is_symbol(value) -> bool:
    return isinstance(value, str) and value and value == value.upper()
