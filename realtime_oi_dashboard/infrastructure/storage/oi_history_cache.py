"""In-memory OI history cache entries and validity helpers."""

from __future__ import annotations

from dataclasses import dataclass

from realtime_oi_dashboard.domain.oi.history_points import (
    HISTORY_BASELINE_TOLERANCE_MS,
)


HistoryPoint = tuple[int, float, float | None]


@dataclass(frozen=True, slots=True)
class OiHistoryCacheEntry:
    refresh_deadline: float
    past_24h_point: HistoryPoint | None
    past_7d_point: HistoryPoint | None

    def is_fresh(self, now: float) -> bool:
        return now < self.refresh_deadline


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
