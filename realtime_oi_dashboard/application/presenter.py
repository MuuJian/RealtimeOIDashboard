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
        cvd_state_provider=None,
        monotonic=time.monotonic,
        wall_time=time.time,
    ) -> None:
        self.state_store = state_store
        self.clock = clock
        self.recent_errors = recent_errors
        self.market_cap_count = market_cap_count
        self.schema_version = schema_version
        self.stale_rows_error = stale_rows_error
        self.cvd_state_provider = cvd_state_provider
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
        cvd_state = self._cvd_state()
        state["cvd_meta"] = _cvd_meta(cvd_state)
        rows = self.state_store.copy_rows()
        if rows and self.clock.rows_are_stale(self.wall_time()):
            rows = []
            state["error"] = self.stale_rows_error
        else:
            rows = self._with_cvd(rows, cvd_state)
        state["rows"] = rows
        state["recent_errors"] = self.recent_errors()
        return state

    def _with_cvd(self, rows, cvd_state):
        snapshots = cvd_state.get("rows") if isinstance(cvd_state, dict) else None
        if snapshots is None:
            return [{**row, **_unavailable_cvd()} for row in rows]
        return [
            {
                **row,
                **snapshots.get(row.get("symbol"), _unavailable_cvd("untracked")),
            }
            for row in rows
        ]

    def _cvd_state(self):
        if self.cvd_state_provider is None:
            return {}
        try:
            state = self.cvd_state_provider.get_state()
        except Exception:
            return {}
        return state if isinstance(state, dict) else {}


def _unavailable_cvd(status="unavailable"):
    return {
        "cvd15m": None,
        "cvd15mRatio": None,
        "cvdDirection": None,
        "cvdHealth": "unavailable",
        "cvdAsOf": None,
        "cvdCoverageSeconds": 0,
        "cvdReason": "CVD data unavailable",
        "cvdStatus": status,
        "cvdUpdatedAt": None,
    }


def _cvd_meta(cvd_state):
    meta = cvd_state.get("cvd_meta") if isinstance(cvd_state, dict) else None
    if isinstance(meta, dict):
        return meta
    return {
        "serviceHealth": "unavailable",
        "universeSymbols": 0,
        "desiredShards": 0,
        "activeShards": 0,
        "connectedShards": 0,
        "incomingMessagesPerSecond": 0.0,
        "processingLagMs": 0.0,
        "backfillQueueSize": 0,
        "healthCounts": {
            "warming": 0,
            "live": 0,
            "stale": 0,
            "partial": 0,
            "unavailable": 0,
        },
    }
