"""In-memory dashboard rows and their update times."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class OiUpdate:
    """One symbol update timestamped when its current OI was measured."""

    symbol: str
    row: dict[str, Any]
    measured_at: float


@dataclass(slots=True)
class OiStateStore:
    """Keep update-time and rendered-row mappings synchronized.

    Flat records are copied at every input and output boundary.
    Callers provide synchronization when the store is shared across threads.
    """

    max_age_seconds: float
    update_times: dict[str, float] = field(default_factory=dict)
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.update_times = dict(self.update_times)
        self.rows = _copy_records(self.rows)

    def copy_rows(self) -> list[dict[str, Any]]:
        return [dict(item) for item in self.rows.values()]

    def apply_updates(
        self,
        results: list[OiUpdate | None],
    ) -> int:
        updated_count = 0
        for update in results:
            if update is None:
                continue
            self.rows[update.symbol] = dict(update.row)
            self.update_times[update.symbol] = update.measured_at
            updated_count += 1
        return updated_count

    def retain_symbols(self, active_symbols: set[str]) -> None:
        for mapping in (self.rows, self.update_times):
            for symbol in set(mapping) - active_symbols:
                del mapping[symbol]

    def prune_stale(self, now: float) -> bool:
        all_symbols = set(self.rows) | set(self.update_times)
        stale_symbols = [
            symbol
            for symbol in all_symbols
            if symbol not in self.rows
            or not self._is_recent(self.update_times.get(symbol), now)
        ]
        for symbol in stale_symbols:
            self.rows.pop(symbol, None)
            self.update_times.pop(symbol, None)
        return bool(stale_symbols)

    def clear(self) -> None:
        self.rows.clear()
        self.update_times.clear()

    def _is_recent(self, updated_at: float | None, now: float) -> bool:
        if updated_at is None:
            return False
        age = now - updated_at
        return 0 <= age <= self.max_age_seconds


def _copy_records(
    records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {symbol: dict(item) for symbol, item in records.items()}
