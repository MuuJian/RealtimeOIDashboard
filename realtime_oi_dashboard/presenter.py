"""Stable API presentation for the realtime OI dashboard."""

from __future__ import annotations

import time


class DashboardPresenter:
    """Build the public `/api/oi` payload from prepared in-memory state."""

    def __init__(
        self,
        state_store,
        clock,
        recent_errors,
        market_cap_count,
        *,
        schema_version: int,
        stale_rows_error: str,
        monotonic=time.monotonic,
        wall_time=time.time,
    ) -> None:
        self.state_store = state_store
        self.clock = clock
        self.recent_errors = recent_errors
        self.market_cap_count = market_cap_count
        self.schema_version = schema_version
        self.stale_rows_error = stale_rows_error
        self.monotonic = monotonic
        self.wall_time = wall_time

    def build(self, base_state, active_symbols) -> dict:
        self.state_store.prune_stale(self.monotonic())
        state = dict(base_state)
        state["schema_version"] = self.schema_version
        state["active_symbols"] = list(active_symbols)
        state["total_symbols"] = len(state["active_symbols"])
        state["market_cap_loaded_symbols"] = self.market_cap_count(
            set(state["active_symbols"])
        )
        rows = self.state_store.copy_rows()
        if rows and self.clock.rows_are_stale(self.wall_time()):
            rows = []
            state["error"] = self.stale_rows_error
        state["rows"] = rows
        state["recent_errors"] = self.recent_errors()
        return state
