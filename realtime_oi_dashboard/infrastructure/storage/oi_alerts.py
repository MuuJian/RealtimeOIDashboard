"""Restart-safe persistence for OI alert configuration and history."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from realtime_oi_dashboard.domain.oi_alerts.model import (
    AlertConfig,
    AlertEvent,
    validate_alert_config,
)
from realtime_oi_dashboard.infrastructure.storage.file_io import write_text_atomic


MAX_RECENT_EVENTS = 50


@dataclass(frozen=True, slots=True)
class AlertSnapshot:
    config: AlertConfig = field(default_factory=AlertConfig.default)
    crossed_thresholds: dict[str, set[float]] = field(default_factory=dict)
    events: tuple[AlertEvent, ...] = ()

    @classmethod
    def default(cls) -> "AlertSnapshot":
        return cls()

    def to_payload(self) -> dict:
        events = self.events[-MAX_RECENT_EVENTS:]
        return {
            "config": {
                "enabled": self.config.enabled,
                "thresholds": list(self.config.thresholds),
            },
            "crossed_thresholds": {
                symbol: sorted(thresholds)
                for symbol, thresholds in self.crossed_thresholds.items()
            },
            "events": [
                {
                    "symbol": event.symbol,
                    "oi_value": event.oi_value,
                    "threshold": event.threshold,
                    "signal": event.signal,
                    "triggered_at": event.triggered_at,
                    "delivery_status": event.delivery_status,
                }
                for event in events
            ],
        }

    @classmethod
    def from_payload(cls, payload: object) -> "AlertSnapshot":
        if not isinstance(payload, dict):
            raise ValueError("alert snapshot must be an object")
        config_payload = payload.get("config")
        if not isinstance(config_payload, dict):
            raise ValueError("alert snapshot configuration is missing")
        config = validate_alert_config(
            config_payload.get("enabled"), config_payload.get("thresholds")
        )
        crossed_thresholds = _crossed_thresholds(payload.get("crossed_thresholds"))
        events = _events(payload.get("events"))
        return cls(config, crossed_thresholds, events[-MAX_RECENT_EVENTS:])


class AlertStateRepository:
    """Load and atomically replace the OI-alert state file."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AlertSnapshot:
        try:
            if not self.path.exists():
                return AlertSnapshot.default()
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return AlertSnapshot.from_payload(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return AlertSnapshot.default()

    def save(self, snapshot: AlertSnapshot) -> None:
        payload = snapshot.to_payload()
        write_text_atomic(
            self.path, json.dumps(payload, ensure_ascii=False, allow_nan=False)
        )


def _crossed_thresholds(value: object) -> dict[str, set[float]]:
    if not isinstance(value, dict):
        raise ValueError("crossed thresholds must be an object")
    result = {}
    for symbol, thresholds in value.items():
        if not isinstance(symbol, str) or not isinstance(thresholds, list):
            raise ValueError("crossed threshold entry is invalid")
        result[symbol] = {float(threshold) for threshold in thresholds}
    return result


def _events(value: object) -> tuple[AlertEvent, ...]:
    if not isinstance(value, list):
        raise ValueError("events must be a list")
    try:
        return tuple(
            AlertEvent(
                symbol=event["symbol"],
                oi_value=float(event["oi_value"]),
                threshold=float(event["threshold"]),
                signal=event["signal"],
                triggered_at=event["triggered_at"],
                delivery_status=event["delivery_status"],
            )
            for event in value
            if isinstance(event, dict)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("event is invalid") from exc
