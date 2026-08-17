"""Application boundary for OI alert state, delivery, and persistence."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import replace
from math import isfinite

from realtime_oi_dashboard.application.oi_alerts.engine import AlertEngine
from realtime_oi_dashboard.domain.oi.state import OiUpdate
from realtime_oi_dashboard.domain.oi_alerts.model import (
    AlertConfig,
    AlertEvent,
    SIGNALS,
    validate_alert_config,
)
from realtime_oi_dashboard.infrastructure.storage.oi_alerts import (
    AlertSnapshot,
    AlertStateRepository,
    MAX_RECENT_EVENTS,
)
from realtime_oi_dashboard.infrastructure.telegram.notifier import TelegramNotifier


class OiAlertService:
    """Own alert mutation, atomic snapshots, and notifier callbacks."""

    def __init__(
        self,
        repository: AlertStateRepository,
        *,
        notifier_factory=TelegramNotifier,
        notifier_stop_timeout=5,
    ) -> None:
        self._repository = repository
        self._lock = threading.RLock()
        self._notifier_stop_timeout = notifier_stop_timeout
        snapshot = repository.load()
        self._engine = AlertEngine(snapshot.config)
        self._events = list(snapshot.events[-MAX_RECENT_EVENTS:])
        self._storage_load_error = repository.load_error
        self._notifier = notifier_factory(mark_delivery=self._mark_delivery)

    def start(self) -> None:
        self._notifier.start()

    def close(self) -> None:
        self._notifier.stop(timeout=self._notifier_stop_timeout)

    def observe_updates(
        self,
        updates: Sequence[OiUpdate | None],
        *,
        triggered_at: str,
    ) -> list[AlertEvent]:
        """Evaluate valid applied updates, persist state, then queue delivery."""
        with self._lock:
            events = []
            for update in updates:
                if update is None:
                    continue
                oi_value = _oi_value(update.row)
                if oi_value is None:
                    continue
                events.extend(
                    self._engine.observe(update.symbol, oi_value, triggered_at)
                )
            if events:
                self._events.extend(events)
                self._bound_events_unlocked()
            self._save_unlocked()

        for event in events:
            self._notifier.enqueue(event)
        return events

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def get_state(self, rows: Mapping[str, Mapping[str, object]]) -> dict:
        with self._lock:
            payload = self._snapshot_unlocked().to_payload()
            payload["notifier"] = self._notifier.get_status()
            payload["storage"] = {
                "status": "load_error" if self._storage_load_error else "ok",
                "last_error": self._storage_load_error,
            }
            payload["active"] = _active_alert_rows(
                rows,
                self._engine.config,
                self._events,
            )
            return payload

    def update_config(
        self,
        payload: Mapping[str, object],
        rows: Mapping[str, Mapping[str, object]],
    ) -> dict:
        if not isinstance(payload, Mapping):
            raise ValueError("alert configuration must be an object")
        config = validate_alert_config(
            payload.get("enabled"),
            payload.get("thresholds"),
        )
        with self._lock:
            self._engine.set_config(config, _row_oi_values(rows))
            self._save_unlocked()
        return self.get_state(rows)

    def send_test_message(self) -> dict:
        queued = self._notifier.send_test_message()
        return {"queued": queued, "notifier": self._notifier.get_status()}

    def _mark_delivery(
        self,
        event: AlertEvent,
        status: str,
        error: str | None,
        attempted_at: str | None,
    ) -> None:
        with self._lock:
            for index, candidate in enumerate(self._events):
                if candidate is event:
                    failure_reason = _safe_failure_reason(error) if status == "failed" else None
                    if status == "failed" and not attempted_at:
                        attempted_at = candidate.triggered_at
                    self._events[index] = replace(
                        candidate,
                        delivery_status=status,
                        failure_reason=failure_reason,
                        last_attempt_at=attempted_at,
                    )
                    self._bound_events_unlocked()
                    self._save_unlocked()
                    break

    def _bound_events_unlocked(self) -> None:
        if len(self._events) > MAX_RECENT_EVENTS:
            self._events = self._events[-MAX_RECENT_EVENTS:]

    def _snapshot_unlocked(self) -> AlertSnapshot:
        return AlertSnapshot(
            config=self._engine.config,
            crossed_thresholds={
                symbol: set(thresholds)
                for symbol, thresholds in self._engine.crossed_thresholds.items()
            },
            events=tuple(self._events),
        )

    def _save_unlocked(self) -> None:
        self._repository.save(self._snapshot_unlocked())


def _oi_value(row: Mapping[str, object]) -> float | None:
    value = row.get("currentOiValue")
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) and parsed >= 0 else None


def _row_oi_values(rows: Mapping[str, Mapping[str, object]]) -> dict[str, float]:
    values = {}
    for symbol, row in rows.items():
        oi_value = _oi_value(row)
        if oi_value is not None:
            values[symbol] = oi_value
    return values


def _active_alert_rows(
    rows: Mapping[str, Mapping[str, object]],
    config: AlertConfig,
    events: Sequence[AlertEvent],
) -> list[dict]:
    last_trigger_by_symbol = {
        event.symbol: event.triggered_at
        for event in events
    }
    active = []
    for symbol, row in rows.items():
        oi_value = _oi_value(row)
        if oi_value is None:
            continue
        crossings = [
            (threshold, signal)
            for threshold, signal in zip(config.thresholds, SIGNALS)
            if oi_value >= threshold
        ]
        if crossings:
            threshold, signal = crossings[-1]
            active.append(
                {
                    "symbol": symbol,
                    "oi_value": oi_value,
                    "threshold": threshold,
                    "signal": signal,
                    "last_triggered_at": last_trigger_by_symbol.get(symbol),
                }
            )
    return active


def _safe_failure_reason(error: str | None) -> str:
    if error == "delivery queue is full":
        return error
    return "Telegram delivery failed"
