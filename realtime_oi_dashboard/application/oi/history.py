"""Load and cache historical open-interest baselines."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.storage.oi_history_cache import (
    HistoryPoint,
    OiHistoryCacheEntry,
    remaining_valid_seconds,
)
from realtime_oi_dashboard.domain.oi.history_points import (
    HOUR_MS,
    calculate_change_percent,
    history_open_interest_point,
    history_point_is_usable,
    history_point_price,
    history_point_value,
    parse_oi_history_points,
)
from realtime_oi_dashboard.domain.parsing import optional_float


OI_HISTORY_CACHE_SECONDS = 60 * 60
OI_HISTORY_RETRY_SECONDS = 60
DOMINANCE_CHART_INTERVAL_MS = 4 * HOUR_MS
DOMINANCE_HISTORY_RETENTION_MS = 7 * 24 * HOUR_MS
DOMINANCE_GROUPS = ("btc", "eth", "other")
DOMINANCE_SYMBOLS = {
    "BTCUSDT": "btc",
    "ETHUSDT": "eth",
}


class OiHistoryService:
    """Return 24h/7d OI changes using bounded, timestamped baselines."""

    def __init__(
        self,
        fetch_history: Callable[[str], object],
        record_error: Callable[[str, Exception], None],
    ) -> None:
        self._fetch_history = fetch_history
        self._record_error = record_error
        self._lock = threading.Lock()
        self._cache: dict[str, OiHistoryCacheEntry] = {}
        self._value_series: dict[str, tuple[tuple[int, float], ...]] = {}
        self._active_symbols: frozenset[str] | None = None
        self._dominance_history_cache: tuple[dict[str, float | int], ...] = ()
        self._dominance_history_dirty = True

    def get_changes(
        self,
        symbol: str,
        current_oi: float,
        current_price: float,
        current_timestamp_ms: int,
    ) -> dict[str, float | None]:
        baselines = self._get_baselines(symbol, current_timestamp_ms)
        price_7d_baseline = history_point_price(
            baselines.past_7d_point,
            baselines.target_7d_ms,
        )

        return {
            "oi24hChangePercent": calculate_change_percent(
                current_oi,
                history_point_value(
                    baselines.past_24h_point,
                    baselines.target_24h_ms,
                ),
            ),
            "oi7dChangePercent": calculate_change_percent(
                current_oi,
                history_point_value(
                    baselines.past_7d_point,
                    baselines.target_7d_ms,
                ),
            ),
            "price7dBaseline": price_7d_baseline,
            "price7dChangePercent": calculate_change_percent(
                current_price,
                price_7d_baseline,
            ),
        }

    def _get_baselines(
        self,
        symbol: str,
        current_timestamp_ms: int,
    ) -> _Baselines:
        target_24h_ms, target_7d_ms = _target_timestamps(current_timestamp_ms)
        cached = self._get_cached(symbol)
        if (
            cached is not None
            and cached.is_fresh(time.monotonic())
            and _cached_points_cover_targets(
                cached,
                target_24h_ms,
                target_7d_ms,
            )
        ):
            return _Baselines(
                target_24h_ms=target_24h_ms,
                target_7d_ms=target_7d_ms,
                past_24h_point=cached.past_24h_point,
                past_7d_point=cached.past_7d_point,
            )

        history_points = None
        retry_in = None
        try:
            history_points = [
                point
                for point in parse_oi_history_points(self._fetch_history(symbol))
                if point[0] <= current_timestamp_ms
            ]
            if not history_points:
                raise ValueError("OI history response contains no valid points")
        except PollingStopped:
            raise
        except Exception as exc:
            history_points = None
            self._record_error(symbol, exc)
            past_24h_point = (
                cached.past_24h_point if cached is not None else None
            )
            past_7d_point = (
                cached.past_7d_point if cached is not None else None
            )
            retry_in = min(
                OI_HISTORY_CACHE_SECONDS,
                OI_HISTORY_RETRY_SECONDS,
            )

        if history_points is not None:
            self._store_value_series(symbol, history_points)
            past_24h_point = self._find_point(
                symbol,
                history_points,
                target_24h_ms,
                "24h",
            )
            past_7d_point = self._find_point(
                symbol,
                history_points,
                target_7d_ms,
                "7d",
            )

        self._store(
            symbol,
            past_24h_point,
            past_7d_point,
            target_24h_ms,
            target_7d_ms,
            retry_in=retry_in,
        )
        return _Baselines(
            target_24h_ms=target_24h_ms,
            target_7d_ms=target_7d_ms,
            past_24h_point=past_24h_point,
            past_7d_point=past_7d_point,
        )

    def _get_cached(
        self,
        symbol: str,
    ) -> OiHistoryCacheEntry | None:
        with self._lock:
            return self._cache.get(symbol)

    def _find_point(
        self,
        symbol: str,
        history_points,
        target_timestamp_ms: int,
        label: str,
    ) -> HistoryPoint | None:
        try:
            return history_open_interest_point(
                history_points,
                target_timestamp_ms,
                label,
            )
        except ValueError as exc:
            self._record_error(symbol, exc)
            return None

    def _store(
        self,
        symbol: str,
        past_24h_point: HistoryPoint | None,
        past_7d_point: HistoryPoint | None,
        target_24h_ms: int,
        target_7d_ms: int,
        *,
        retry_in: float | None,
    ) -> None:
        refresh_in = OI_HISTORY_CACHE_SECONDS
        if retry_in is not None:
            refresh_in = min(max(retry_in, 0), refresh_in)
        else:
            for point, target_timestamp_ms in (
                (past_24h_point, target_24h_ms),
                (past_7d_point, target_7d_ms),
            ):
                remaining_seconds = remaining_valid_seconds(
                    point,
                    target_timestamp_ms,
                )
                if remaining_seconds is not None:
                    refresh_in = min(refresh_in, remaining_seconds)
        with self._lock:
            self._cache[symbol] = OiHistoryCacheEntry(
                refresh_deadline=time.monotonic() + refresh_in,
                past_24h_point=past_24h_point,
                past_7d_point=past_7d_point,
            )

    def retain_symbols(self, active_symbols: set[str]) -> None:
        with self._lock:
            next_active_symbols = frozenset(active_symbols)
            active_symbols_changed = next_active_symbols != self._active_symbols
            self._active_symbols = next_active_symbols
            self._cache = {
                symbol: item
                for symbol, item in self._cache.items()
                if symbol in active_symbols
            }
            retained_series = {
                symbol: series
                for symbol, series in self._value_series.items()
                if symbol in active_symbols
            }
            if active_symbols_changed or retained_series != self._value_series:
                self._value_series = retained_series
                self._dominance_history_dirty = True

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._value_series.clear()
            self._dominance_history_cache = ()
            self._dominance_history_dirty = True

    def get_dominance_history(self) -> list[dict[str, float | int]]:
        """Aggregate cached notional OI into four-hour chart shares."""
        with self._lock:
            if self._dominance_history_dirty:
                self._dominance_history_cache = tuple(
                    _aggregate_dominance_history(
                        self._value_series,
                        self._active_symbols,
                    )
                )
                self._dominance_history_dirty = False
            return [dict(point) for point in self._dominance_history_cache]

    def _store_value_series(self, symbol, history_points) -> None:
        values_by_interval = {}
        for timestamp_ms, item in history_points:
            value = optional_float(item.get("sumOpenInterestValue"))
            if value is None or value <= 0:
                continue
            chart_timestamp = (
                timestamp_ms
                // DOMINANCE_CHART_INTERVAL_MS
                * DOMINANCE_CHART_INTERVAL_MS
            )
            values_by_interval[chart_timestamp] = value
        if not values_by_interval:
            self._record_error(
                symbol,
                ValueError("OI history response contains no valid notional values"),
            )
            return
        with self._lock:
            retained_values = dict(self._value_series.get(symbol, ()))
            retained_values.update(values_by_interval)
            newest_timestamp = max(retained_values)
            cutoff_timestamp = newest_timestamp - DOMINANCE_HISTORY_RETENTION_MS
            series = tuple(
                (timestamp_ms, value)
                for timestamp_ms, value in sorted(retained_values.items())
                if timestamp_ms >= cutoff_timestamp
            )
            if self._value_series.get(symbol) == series:
                return
            self._value_series[symbol] = series
            self._dominance_history_dirty = True


@dataclass(frozen=True, slots=True)
class _Baselines:
    target_24h_ms: int
    target_7d_ms: int
    past_24h_point: HistoryPoint | None
    past_7d_point: HistoryPoint | None


def _aggregate_dominance_history(value_series, active_symbols=None):
    if active_symbols is not None and (
        not active_symbols or not active_symbols.issubset(value_series)
    ):
        return []

    totals_by_interval = {}
    symbols_by_interval = {}
    for symbol, series in value_series.items():
        group = DOMINANCE_SYMBOLS.get(symbol, "other")
        for timestamp_ms, value in series:
            totals = totals_by_interval.setdefault(
                timestamp_ms,
                {key: 0.0 for key in DOMINANCE_GROUPS},
            )
            totals[group] += value
            symbols_by_interval.setdefault(timestamp_ms, set()).add(symbol)

    result = []
    for timestamp_ms in sorted(totals_by_interval):
        if (
            active_symbols is not None
            and symbols_by_interval[timestamp_ms] != active_symbols
        ):
            continue
        totals = totals_by_interval[timestamp_ms]
        if any(
            not isfinite(totals[key]) or totals[key] <= 0
            for key in DOMINANCE_GROUPS
        ):
            continue
        total = sum(totals.values())
        if not isfinite(total) or total <= 0:
            continue
        result.append({
            "timestamp": timestamp_ms,
            **{
                key: totals[key] / total * 100
                for key in DOMINANCE_GROUPS
            },
            **{
                f"{key}Value": totals[key]
                for key in DOMINANCE_GROUPS
            },
        })
    return result


def _target_timestamps(current_timestamp_ms: int) -> tuple[int, int]:
    return (
        current_timestamp_ms - 24 * HOUR_MS,
        current_timestamp_ms - 7 * 24 * HOUR_MS,
    )


def _cached_points_cover_targets(
    cached: OiHistoryCacheEntry,
    target_24h_ms: int,
    target_7d_ms: int,
) -> bool:
    return all(
        point is None or history_point_is_usable(point, target_timestamp_ms)
        for point, target_timestamp_ms in (
            (cached.past_24h_point, target_24h_ms),
            (cached.past_7d_point, target_7d_ms),
        )
    )
