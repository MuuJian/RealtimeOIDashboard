"""Bounded in-memory cache state for dashboard market responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CacheLookup:
    hit: bool
    value: dict[str, dict[str, Any]] | None


@dataclass(slots=True)
class MarketCache:
    """Track refresh and final-staleness deadlines for flat symbol records.

    Callers provide synchronization when the cache is shared across threads.
    """

    cache_seconds: float
    stale_grace_seconds: float
    value: dict[str, dict[str, Any]] | None = None
    refresh_deadline: float = 0.0
    stale_deadline: float = 0.0

    @property
    def enabled(self) -> bool:
        return self.cache_seconds > 0

    def get_fresh(self, now: float) -> CacheLookup:
        if not self.enabled or now >= self.refresh_deadline:
            return CacheLookup(False, None)
        if self.value is not None and now >= self.stale_deadline:
            return CacheLookup(False, None)
        return CacheLookup(True, self.value)

    def copy_for_merge(
        self,
        now: float,
        symbols: set[str],
    ) -> dict[str, dict[str, Any]]:
        if self.enabled and self.value is not None and now < self.stale_deadline:
            cached_values = self.value
            selected_values = {
                symbol: dict(cached_values[symbol])
                for symbol in symbols
                if symbol in cached_values
            }
            return selected_values
        return {}

    def store(
        self,
        value: dict[str, dict[str, Any]],
        now: float,
        refresh_in: float,
        *,
        preserve_stale_deadline: bool = False,
    ) -> None:
        if not self.enabled:
            self.clear()
            return

        previous_stale_deadline = self.stale_deadline
        self.value = value
        self.refresh_deadline = now + max(refresh_in, 0)
        if preserve_stale_deadline:
            self.stale_deadline = previous_stale_deadline
            self.refresh_deadline = min(
                self.refresh_deadline,
                self.stale_deadline,
            )
            return
        self.stale_deadline = self.refresh_deadline + self.stale_grace_seconds

    def fallback_after_failure(
        self,
        now: float,
        retry_in: float,
        *,
        throttle_without_value: bool,
    ) -> CacheLookup:
        if not self.enabled:
            self.clear()
            return CacheLookup(False, None)

        cached = self.value
        cache_is_usable = (
            cached is not None
            and now < self.stale_deadline
        )
        if cache_is_usable:
            self.refresh_deadline = now + max(retry_in, 0)
            self.refresh_deadline = min(
                self.refresh_deadline,
                self.stale_deadline,
            )
        elif throttle_without_value:
            self.refresh_deadline = now + max(retry_in, 0)
        else:
            self.refresh_deadline = 0.0
        if not cache_is_usable:
            self.value = None
            self.stale_deadline = 0.0
        return CacheLookup(
            cache_is_usable,
            cached if cache_is_usable else None,
        )

    def retain_symbols(self, active_symbols: set[str]) -> None:
        if self.value is None:
            return
        self.value = {
            symbol: item
            for symbol, item in self.value.items()
            if symbol in active_symbols
        }
        if not self.value:
            self.clear()

    def clear(self) -> None:
        self.value = None
        self.refresh_deadline = 0.0
        self.stale_deadline = 0.0
