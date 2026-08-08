"""Historical open-interest loading, baseline selection, and caching."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.oi_history_cache import (
    HistoryPoint,
    OiHistoryCacheEntry,
    export_history_cache,
    remaining_valid_seconds,
    restore_history_cache,
)
from realtime_oi_dashboard.domain.oi_history_points import (
    HOUR_MS,
    calculate_change_percent,
    history_open_interest_point,
    history_point_price,
    history_point_value,
    parse_oi_history_points,
)


OI_HISTORY_CACHE_SECONDS = 60 * 60
OI_HISTORY_RETRY_SECONDS = 60


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

    def get_changes(
        self,
        symbol: str,
        current_oi: float,
        current_price: float,
    ) -> dict[str, float | None]:
        baselines = self._get_baselines(symbol)
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
    ) -> _Baselines:
        cached = self._get_cached(symbol)
        if (
            cached is not None
            and cached.is_fresh(time.monotonic())
        ):
            target_24h_ms, target_7d_ms = _target_timestamps()
            return _Baselines(
                target_24h_ms=target_24h_ms,
                target_7d_ms=target_7d_ms,
                past_24h_point=cached.past_24h_point,
                past_7d_point=cached.past_7d_point,
            )

        history_points = None
        retry_in = None
        try:
            history_points = parse_oi_history_points(
                self._fetch_history(symbol)
            )
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

        target_24h_ms, target_7d_ms = _target_timestamps()
        if history_points is not None:
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
            self._cache = {
                symbol: item
                for symbol, item in self._cache.items()
                if symbol in active_symbols
            }

    def export_cache(self) -> dict[str, dict[str, object]]:
        """Return restart-safe history baselines with their real expiry time."""
        monotonic_now = time.monotonic()
        wall_now = time.time()
        with self._lock:
            cache = dict(self._cache)
        return export_history_cache(
            cache,
            monotonic_now=monotonic_now,
            wall_now=wall_now,
        )

    def restore_cache(self, records: object) -> int:
        """Restore still-fresh baselines without extending their cache life."""
        if not isinstance(records, dict):
            return 0

        wall_now = time.time()
        monotonic_now = time.monotonic()
        target_24h_ms, target_7d_ms = _target_timestamps()
        restored = restore_history_cache(
            records,
            cache_seconds=OI_HISTORY_CACHE_SECONDS,
            target_24h_ms=target_24h_ms,
            target_7d_ms=target_7d_ms,
            wall_now=wall_now,
            monotonic_now=monotonic_now,
        )

        with self._lock:
            self._cache.update(restored)
        return len(restored)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


@dataclass(frozen=True, slots=True)
class _Baselines:
    target_24h_ms: int
    target_7d_ms: int
    past_24h_point: HistoryPoint | None
    past_7d_point: HistoryPoint | None


def _target_timestamps() -> tuple[int, int]:
    now_ms = int(time.time() * 1000)
    return now_ms - 24 * HOUR_MS, now_ms - 7 * 24 * HOUR_MS
