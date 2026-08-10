"""Publish immutable signal-scan snapshots and track their freshness."""

from __future__ import annotations

import time
from datetime import datetime
from math import isfinite

from realtime_oi_dashboard.domain.errors import PollingStopped


SIGNAL_SCAN_API_SCHEMA_VERSION = 2
MAX_ERROR_TEXT_LENGTH = 512


class SignalScanStateStore:
    """Keep the last scan result separate from polling and shutdown logic."""

    def __init__(self, lock, stop_event, error_log, *, max_age_seconds: float):
        self._lock = lock
        self._stop_event = stop_event
        self._error_log = error_log
        self.max_age_seconds = max_age_seconds
        self.state = empty_state()
        self.last_success_wall_clock = None
        self.last_success_monotonic = None

    def publish_success(
        self,
        signals: dict[str, list[dict]],
        *,
        scan_total: int,
        scan_succeeded: int,
    ) -> None:
        saved_at = time.time()
        saved_at_monotonic = time.monotonic()
        with self._lock:
            if self._stop_event.is_set():
                raise PollingStopped
            self.last_success_wall_clock = saved_at
            self.last_success_monotonic = saved_at_monotonic
            self.state = empty_state()
            self.state.update(
                {
                    "bulls": copy_rows(signals["bulls"]),
                    "bears": copy_rows(signals["bears"]),
                    "spikes": copy_rows(signals["spikes"]),
                    "saved_at": iso_now(saved_at),
                    "scan_total": scan_total,
                    "scan_succeeded": scan_succeeded,
                    "partial": scan_succeeded < scan_total,
                }
            )

    def mark_failed(
        self,
        error: object,
        *,
        scan_total: int = 0,
        scan_succeeded: int = 0,
    ) -> None:
        message = error_text(error)
        with self._lock:
            if self._stop_event.is_set():
                return
            saved_at = self.state["saved_at"]
            self.state = empty_state()
            self.state.update(
                {
                    "saved_at": saved_at,
                    "error": message,
                    "scan_total": scan_total,
                    "scan_succeeded": scan_succeeded,
                    "partial": scan_total > scan_succeeded,
                }
            )

    def snapshot(self) -> dict:
        with self._lock:
            state = copy_state(self.state)
            state["schema_version"] = SIGNAL_SCAN_API_SCHEMA_VERSION
            state["recent_errors"] = self._error_log.recent()
            if (
                state["saved_at"] is not None
                and state["error"] is None
                and self.is_stale()
            ):
                state["bulls"] = []
                state["bears"] = []
                state["spikes"] = []
                state["error"] = (
                    f"訊號資料已超過 {int(self.max_age_seconds)} 秒，等待重新掃描"
                )
            return state

    def is_stale(self) -> bool:
        if self.last_success_monotonic is None:
            return True
        age = time.monotonic() - self.last_success_monotonic
        return (
            not isfinite(age)
            or age < 0
            or age > self.max_age_seconds
        )


def error_text(error: object) -> str:
    message = str(error).strip()
    if message:
        if len(message) <= MAX_ERROR_TEXT_LENGTH:
            return message
        return f"{message[:MAX_ERROR_TEXT_LENGTH - 3]}..."
    if isinstance(error, BaseException):
        return error.__class__.__name__
    return "signal scan failed"


def iso_now(wall_time):
    return datetime.fromtimestamp(wall_time).astimezone().isoformat(
        timespec="seconds"
    )


def copy_rows(rows: list[dict]) -> list[dict]:
    return [dict(row) for row in rows]


def empty_state() -> dict:
    return {
        "bulls": [],
        "bears": [],
        "spikes": [],
        "saved_at": None,
        "error": None,
        "scan_total": 0,
        "scan_succeeded": 0,
        "partial": False,
    }


def copy_state(state: dict) -> dict:
    return {
        "bulls": copy_rows(state["bulls"]),
        "bears": copy_rows(state["bears"]),
        "spikes": copy_rows(state["spikes"]),
        "saved_at": state["saved_at"],
        "error": state["error"],
        "scan_total": state["scan_total"],
        "scan_succeeded": state["scan_succeeded"],
        "partial": state["partial"],
    }
