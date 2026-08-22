"""Application boundary for OI alert state, delivery, and persistence."""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import replace
from math import isfinite

from realtime_oi_dashboard.application.oi_alerts.engine import AlertEngine
from realtime_oi_dashboard.application.oi_alerts.features import (
    ExpansionAlertEngine,
    SignalFeatureTracker,
    active_feature_rows,
)
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
        self._last_triggered_at = {
            symbol: dict(trigger_times)
            for symbol, trigger_times in snapshot.last_triggered_at.items()
        }
        self._storage_load_error = repository.load_error
        self._notifier = notifier_factory(mark_delivery=self._mark_delivery)
        self._feature_tracker = SignalFeatureTracker()
        self._expansion_engine = ExpansionAlertEngine()
        self._pending_replayed = False

    def start(self) -> None:
        self._notifier.start()
        with self._lock:
            if self._pending_replayed:
                return
            pending = [
                event
                for event in self._events
                if event.delivery_status in {"pending", "queued"}
            ]
            self._pending_replayed = True
        for event in pending:
            self._notifier.enqueue(event)

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
            observed_symbols = set()
            dirty = False
            for update in updates:
                if update is None:
                    continue
                oi_value = _oi_value(update.row)
                if oi_value is None:
                    continue
                observed_symbols.add(update.symbol)
                previous_crossed = set(
                    self._engine.crossed_thresholds.get(update.symbol, set())
                )
                event_time, exchange_timestamp_ms = _event_time(
                    update.row, triggered_at
                )
                scale_events = self._engine.observe(
                    update.symbol, oi_value, event_time
                )
                if self._engine.crossed_thresholds.get(update.symbol, set()) != previous_crossed:
                    dirty = True
                for event in scale_events:
                    events.append(
                        replace(
                            event,
                            exchange_timestamp_ms=exchange_timestamp_ms,
                            explanation=(
                                f"{event.signal}: total OI reached "
                                f"${event.oi_value:,.0f}"
                            ),
                        )
                    )
                feature = self._feature_tracker.observe(
                    update.symbol,
                    dict(update.row),
                    window_minutes=self._engine.config.change_window_minutes,
                )
                if feature is not None:
                    events.extend(
                        self._expansion_engine.observe(feature, self._engine.config)
                    )
            if events:
                dirty = True
                for event in events:
                    if event.event_type != "oi_scale":
                        continue
                    self._last_triggered_at.setdefault(event.symbol, {})[
                        event.threshold
                    ] = event.triggered_at
                self._events.extend(events)
                self._bound_events_unlocked()
            for symbol in observed_symbols:
                trigger_times = self._last_triggered_at.get(symbol)
                if trigger_times is None:
                    continue
                crossed_thresholds = self._engine.crossed_thresholds.get(
                    symbol, set()
                )
                for threshold in set(trigger_times) - crossed_thresholds:
                    del trigger_times[threshold]
                    dirty = True
                if not trigger_times:
                    del self._last_triggered_at[symbol]
                    dirty = True
            if dirty:
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
                self._last_triggered_at,
            )
            payload["active"].extend(
                active_feature_rows(
                    self._feature_tracker.payload(), self._engine.config
                )
            )
            payload["features"] = self._feature_tracker.payload()
            return payload

    def get_features(self) -> dict[str, dict]:
        with self._lock:
            return self._feature_tracker.payload()

    def retain_symbols(self, symbols: set[str]) -> None:
        with self._lock:
            self._engine.retain_symbols(symbols)
            self._feature_tracker.retain_symbols(symbols)
            self._expansion_engine.retain_symbols(symbols)

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
            scale_alerts_enabled=payload.get("scale_alerts_enabled", True),
            change_window_minutes=payload.get("change_window_minutes", 15),
            min_oi_change_percent=payload.get("min_oi_change_percent", 3.0),
            min_price_change_percent=payload.get("min_price_change_percent", 0.5),
            require_cvd_confirmation=payload.get("require_cvd_confirmation", False),
            cooldown_minutes=payload.get("cooldown_minutes", 30),
            symbols=payload.get("symbols", ()),
        )
        with self._lock:
            self._engine.set_config(config, _row_oi_values(rows))
            self._feature_tracker.set_window(config.change_window_minutes)
            self._expansion_engine.reset()
            configured_thresholds = set(config.thresholds)
            self._last_triggered_at = {
                symbol: {
                    threshold: triggered_at
                    for threshold, triggered_at in trigger_times.items()
                    if threshold in configured_thresholds
                }
                for symbol, trigger_times in self._last_triggered_at.items()
                if any(
                    threshold in configured_thresholds
                    for threshold in trigger_times
                )
            }
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
                if candidate.event_id == event.event_id:
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
            last_triggered_at={
                symbol: dict(trigger_times)
                for symbol, trigger_times in self._last_triggered_at.items()
            },
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
    last_triggered_at: Mapping[str, Mapping[float, str]],
) -> list[dict]:
    if not config.scale_alerts_enabled:
        return []
    active = []
    for symbol, row in rows.items():
        if config.symbols and symbol not in config.symbols:
            continue
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
            as_of, exchange_timestamp_ms = _event_time(row, "")
            active.append(
                {
                    "symbol": symbol,
                    "event_type": "oi_scale",
                    "oi_value": oi_value,
                    "threshold": threshold,
                    "signal": signal,
                    "oi_change_percent": None,
                    "price_change_percent": None,
                    "explanation": (
                        f"{signal}: total OI is ${oi_value:,.0f}"
                    ),
                    "as_of": as_of or None,
                    "exchange_timestamp_ms": exchange_timestamp_ms,
                    "last_triggered_at": last_triggered_at.get(symbol, {}).get(
                        threshold
                    ),
                }
            )
    return active


def _event_time(row: Mapping[str, object], fallback: str) -> tuple[str, int | None]:
    value = row.get("oiUpdatedAt")
    if not isinstance(value, bool):
        try:
            timestamp_ms = int(value)
            if timestamp_ms > 0:
                from datetime import datetime, timezone

                return (
                    datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    timestamp_ms,
                )
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    return fallback, None


def _safe_failure_reason(error: str | None) -> str:
    if error == "delivery queue is full":
        return error
    return "Telegram delivery failed"
