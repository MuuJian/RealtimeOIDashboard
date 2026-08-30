"""Present stable API payloads for the OI dashboard."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
import time


_CVD_FIELDS = (
    "cvd15m",
    "cvd15mRatio",
    "cvdDirection",
    "cvdHealth",
    "cvdAsOf",
    "cvdCoverageSeconds",
    "cvdReason",
    "cvdStatus",
    "cvdUpdatedAt",
)
_CVD_STATUSES = {
    "buying",
    "selling",
    "neutral",
    "collecting",
    "untracked",
    "unavailable",
}
_CVD_DIRECTIONS = {"buying", "selling", "neutral"}
_CVD_HEALTH = {"warming", "live", "stale", "partial", "unavailable"}
_CVD_HEALTH_COUNT_KEYS = ("warming", "live", "stale", "partial", "unavailable")
_MAX_SAFE_INTEGER = 2**53 - 1


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
        dominance_history_provider=None,
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
        self.dominance_history_provider = dominance_history_provider or (lambda: [])
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
        state["oi_dominance_history"] = self.dominance_history_provider()
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
        snapshots = cvd_state.get("rows") if isinstance(cvd_state, Mapping) else None
        if not isinstance(snapshots, Mapping):
            return [{**row, **_unavailable_cvd()} for row in rows]
        enriched_rows = []
        for row in rows:
            symbol = row.get("symbol")
            snapshot = snapshots.get(symbol)
            if snapshot is None:
                public_cvd = _unavailable_cvd("untracked")
            else:
                public_cvd = _public_cvd_fields(snapshot)
            enriched_rows.append({**row, **public_cvd})
        return enriched_rows

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
    meta = cvd_state.get("cvd_meta") if isinstance(cvd_state, Mapping) else None
    if not isinstance(meta, Mapping):
        return _unavailable_cvd_meta()

    health_counts = meta.get("healthCounts")
    if not isinstance(health_counts, Mapping):
        return _unavailable_cvd_meta()

    integer_fields = (
        "universeSymbols",
        "desiredShards",
        "activeShards",
        "connectedShards",
        "backfillQueueSize",
    )
    if any(not _is_non_negative_safe_integer(meta.get(key)) for key in integer_fields):
        return _unavailable_cvd_meta()
    if any(
        not _is_non_negative_safe_integer(health_counts.get(key))
        for key in _CVD_HEALTH_COUNT_KEYS
    ):
        return _unavailable_cvd_meta()
    if (
        meta.get("serviceHealth") not in _CVD_HEALTH
        or not _is_non_negative_finite_number(meta.get("incomingMessagesPerSecond"))
        or not _is_non_negative_finite_number(meta.get("processingLagMs"))
        or meta["connectedShards"] > meta["activeShards"]
        or meta["activeShards"] > meta["desiredShards"]
        or sum(health_counts[key] for key in _CVD_HEALTH_COUNT_KEYS)
        > meta["universeSymbols"]
    ):
        return _unavailable_cvd_meta()

    public_meta = {
        "serviceHealth": meta["serviceHealth"],
        **{key: meta[key] for key in integer_fields},
        "incomingMessagesPerSecond": meta["incomingMessagesPerSecond"],
        "processingLagMs": meta["processingLagMs"],
        "healthCounts": {
            key: health_counts[key] for key in _CVD_HEALTH_COUNT_KEYS
        },
    }
    snapshot_error = meta.get("snapshotError")
    if snapshot_error is None or isinstance(snapshot_error, str):
        public_meta["snapshotError"] = snapshot_error
    return public_meta


def _public_cvd_fields(snapshot):
    if not isinstance(snapshot, Mapping):
        return _unavailable_cvd()
    if any(key not in snapshot for key in _CVD_FIELDS):
        return _unavailable_cvd()

    public_cvd = {key: snapshot[key] for key in _CVD_FIELDS}
    if (
        not _is_optional_finite_number(public_cvd["cvd15m"])
        or not _is_optional_finite_number(public_cvd["cvd15mRatio"])
        or public_cvd["cvdDirection"] is not None
        and public_cvd["cvdDirection"] not in _CVD_DIRECTIONS
        or public_cvd["cvdHealth"] not in _CVD_HEALTH
        or not _is_optional_timestamp(public_cvd["cvdAsOf"])
        or not _is_non_negative_finite_number(public_cvd["cvdCoverageSeconds"])
        or public_cvd["cvdReason"] is not None
        and not isinstance(public_cvd["cvdReason"], str)
        or public_cvd["cvdStatus"] not in _CVD_STATUSES
        or not _is_optional_timestamp(public_cvd["cvdUpdatedAt"])
    ):
        return _unavailable_cvd()
    return public_cvd


def _is_optional_finite_number(value):
    return value is None or _is_finite_number(value)


def _is_non_negative_finite_number(value):
    return _is_finite_number(value) and value >= 0


def _is_finite_number(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and isfinite(value)
    )


def _is_optional_timestamp(value):
    return value is None or (
        _is_non_negative_safe_integer(value) and value > 0
    )


def _is_non_negative_safe_integer(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and 0 <= value <= _MAX_SAFE_INTEGER
    )


def _unavailable_cvd_meta():
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
