"""Serialize OI history baselines for restart-safe caching."""

from __future__ import annotations

import time
from dataclasses import dataclass

from realtime_oi_dashboard.domain.oi.history_points import (
    HISTORY_BASELINE_TOLERANCE_MS,
    MAX_SAFE_INTEGER,
    history_point_value,
)
from realtime_oi_dashboard.domain.parsing import optional_float, optional_int
from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol


HistoryPoint = tuple[int, float, float | None]


@dataclass(frozen=True, slots=True)
class OiHistoryCacheEntry:
    refresh_deadline: float
    past_24h_point: HistoryPoint | None
    past_7d_point: HistoryPoint | None

    def is_fresh(self, now: float) -> bool:
        return now < self.refresh_deadline


def export_history_cache(
    cache: dict[str, OiHistoryCacheEntry],
    *,
    monotonic_now: float | None = None,
    wall_now: float | None = None,
) -> dict[str, dict[str, object]]:
    monotonic_now = time.monotonic() if monotonic_now is None else monotonic_now
    wall_now = time.time() if wall_now is None else wall_now
    exported = {}
    for symbol, entry in cache.items():
        remaining_seconds = entry.refresh_deadline - monotonic_now
        if remaining_seconds <= 0:
            continue
        exported[symbol] = {
            "refreshAt": wall_now + remaining_seconds,
            "past24hPoint": serialize_history_point(entry.past_24h_point),
            "past7dPoint": serialize_history_point(entry.past_7d_point),
        }
    return exported


def restore_history_cache(
    records: object,
    *,
    cache_seconds: float,
    target_24h_ms: int,
    target_7d_ms: int,
    wall_now: float | None = None,
    monotonic_now: float | None = None,
) -> dict[str, OiHistoryCacheEntry]:
    if cache_seconds <= 0 or not isinstance(records, dict):
        return {}

    wall_now = time.time() if wall_now is None else wall_now
    monotonic_now = time.monotonic() if monotonic_now is None else monotonic_now
    restored = {}
    for symbol, item in records.items():
        if not is_valid_binance_symbol(symbol) or not isinstance(item, dict):
            continue

        refresh_at = optional_float(item.get("refreshAt"))
        if refresh_at is None:
            continue
        remaining_cache_seconds = refresh_at - wall_now
        if remaining_cache_seconds <= 0:
            continue

        past_24h_point = usable_restored_point(
            item.get("past24hPoint"),
            target_24h_ms,
        )
        past_7d_point = usable_restored_point(
            item.get("past7dPoint"),
            target_7d_ms,
        )
        if past_24h_point is None and past_7d_point is None:
            continue

        refresh_in = min(cache_seconds, remaining_cache_seconds)
        for point, target_timestamp_ms in (
            (past_24h_point, target_24h_ms),
            (past_7d_point, target_7d_ms),
        ):
            remaining_valid = remaining_valid_seconds(point, target_timestamp_ms)
            if remaining_valid is not None:
                refresh_in = min(refresh_in, remaining_valid)
        if refresh_in <= 0:
            continue

        restored[symbol] = OiHistoryCacheEntry(
            refresh_deadline=monotonic_now + refresh_in,
            past_24h_point=past_24h_point,
            past_7d_point=past_7d_point,
        )
    return restored


def remaining_valid_seconds(
    point: HistoryPoint | None,
    target_timestamp_ms: int,
) -> float | None:
    if point is None:
        return None
    remaining_ms = (
        point[0]
        + HISTORY_BASELINE_TOLERANCE_MS
        - target_timestamp_ms
    )
    return max(remaining_ms / 1000, 0)


def serialize_history_point(
    point: HistoryPoint | None,
) -> list[float | int | None] | None:
    return list(point) if point is not None else None


def usable_restored_point(
    value: object,
    target_timestamp_ms: int,
) -> HistoryPoint | None:
    point = deserialize_history_point(value)
    if history_point_value(point, target_timestamp_ms) is None:
        return None
    return point


def deserialize_history_point(value: object) -> HistoryPoint | None:
    if not isinstance(value, list) or len(value) != 3:
        return None

    timestamp_ms = optional_int(value[0])
    open_interest = optional_float(value[1])
    implied_price = optional_float(value[2])
    if (
        timestamp_ms is None
        or not 0 < timestamp_ms <= MAX_SAFE_INTEGER
        or open_interest is None
        or open_interest < 0
        or (implied_price is not None and implied_price <= 0)
    ):
        return None
    return timestamp_ms, open_interest, implied_price
