"""Restart-safe persistence for OI alert configuration and history."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from math import isfinite
from pathlib import Path
from uuid import uuid4

from realtime_oi_dashboard.domain.oi_alerts.model import (
    AlertConfig,
    AlertEvent,
    validate_alert_config,
)
from realtime_oi_dashboard.infrastructure.storage.file_io import write_text_atomic


MAX_RECENT_EVENTS = 50
SAFE_LOAD_ERROR = "Saved OI alert state could not be loaded; defaults are active"
_SAFE_FAILURE_REASONS = {
    "Telegram delivery failed",
    "delivery queue is full",
}


@dataclass(frozen=True, slots=True)
class AlertSnapshot:
    config: AlertConfig = field(default_factory=AlertConfig.default)
    crossed_thresholds: dict[str, set[float]] = field(default_factory=dict)
    events: tuple[AlertEvent, ...] = ()
    last_triggered_at: dict[str, dict[float, str]] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "AlertSnapshot":
        return cls()

    def to_payload(self) -> dict:
        events = self.events[-MAX_RECENT_EVENTS:]
        configured_thresholds = set(self.config.thresholds)
        return {
            "config": {
                "enabled": self.config.enabled,
                "thresholds": list(self.config.thresholds),
                "scale_alerts_enabled": self.config.scale_alerts_enabled,
                "change_window_minutes": self.config.change_window_minutes,
                "min_oi_change_percent": self.config.min_oi_change_percent,
                "min_price_change_percent": self.config.min_price_change_percent,
                "require_cvd_confirmation": self.config.require_cvd_confirmation,
                "cooldown_minutes": self.config.cooldown_minutes,
                "symbols": list(self.config.symbols),
            },
            "crossed_thresholds": {
                symbol: sorted(thresholds)
                for symbol, thresholds in self.crossed_thresholds.items()
            },
            "last_triggered_at": {
                symbol: {
                    str(threshold): triggered_at
                    for threshold, triggered_at in trigger_times.items()
                    if threshold in configured_thresholds
                }
                for symbol, trigger_times in self.last_triggered_at.items()
                if any(
                    threshold in configured_thresholds
                    for threshold in trigger_times
                )
            },
            "events": [
                {
                    "symbol": event.symbol,
                    "oi_value": event.oi_value,
                    "threshold": event.threshold,
                    "signal": event.signal,
                    "triggered_at": event.triggered_at,
                    "event_id": event.event_id,
                    "event_type": event.event_type,
                    "oi_change_percent": event.oi_change_percent,
                    "price_change_percent": event.price_change_percent,
                    "explanation": event.explanation,
                    "exchange_timestamp_ms": event.exchange_timestamp_ms,
                    "delivery_status": event.delivery_status,
                    "failure_reason": event.failure_reason,
                    "last_attempt_at": event.last_attempt_at,
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
        _validate_config_booleans(config_payload)
        config = validate_alert_config(
            config_payload.get("enabled"),
            config_payload.get("thresholds"),
            scale_alerts_enabled=config_payload.get(
                "scale_alerts_enabled", config_payload.get("enabled", True)
            ),
            change_window_minutes=config_payload.get("change_window_minutes", 15),
            min_oi_change_percent=config_payload.get("min_oi_change_percent", 3.0),
            min_price_change_percent=config_payload.get("min_price_change_percent", 0.5),
            require_cvd_confirmation=config_payload.get("require_cvd_confirmation", False),
            cooldown_minutes=config_payload.get("cooldown_minutes", 30),
            symbols=config_payload.get("symbols", ()),
        )
        crossed_thresholds = _crossed_thresholds(payload.get("crossed_thresholds"))
        events = _events(payload.get("events"))
        last_triggered_at = _last_triggered_at(
            payload.get("last_triggered_at"),
            config,
            events,
        )
        return cls(
            config,
            crossed_thresholds,
            events[-MAX_RECENT_EVENTS:],
            last_triggered_at,
        )


class AlertStateRepository:
    """Load and atomically replace the OI-alert state file."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.load_error: str | None = None

    def load(self) -> AlertSnapshot:
        self.load_error = None
        try:
            if not self.path.exists():
                return AlertSnapshot.default()
            payload = json.loads(
                self.path.read_text(encoding="utf-8"),
                parse_constant=_reject_json_constant,
            )
            return AlertSnapshot.from_payload(payload)
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self.load_error = SAFE_LOAD_ERROR
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
        if not _is_symbol(symbol) or not isinstance(thresholds, list):
            raise ValueError("crossed threshold entry is invalid")
        parsed_thresholds = {_positive_finite(threshold) for threshold in thresholds}
        result[symbol] = parsed_thresholds
    return result


def _events(value: object) -> tuple[AlertEvent, ...]:
    if not isinstance(value, list):
        raise ValueError("events must be a list")
    if not all(isinstance(event, dict) for event in value):
        raise ValueError("event is invalid")
    try:
        return tuple(_event(event) for event in value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("event is invalid") from exc


def _last_triggered_at(
    value: object,
    config: AlertConfig,
    events: tuple[AlertEvent, ...],
) -> dict[str, dict[float, str]]:
    configured_thresholds = set(config.thresholds)
    if value is None:
        result: dict[str, dict[float, str]] = {}
        for event in events:
            if event.threshold in configured_thresholds:
                result.setdefault(event.symbol, {})[event.threshold] = event.triggered_at
        return result
    if not isinstance(value, dict):
        raise ValueError("last trigger times must be an object")

    result = {}
    for symbol, trigger_times in value.items():
        if not isinstance(symbol, str) or not isinstance(trigger_times, dict):
            raise ValueError("last trigger time entry is invalid")
        parsed_times = {}
        for threshold_text, triggered_at in trigger_times.items():
            try:
                threshold = float(threshold_text)
            except (TypeError, ValueError, OverflowError) as exc:
                raise ValueError("last trigger threshold is invalid") from exc
            if (
                not isfinite(threshold)
                or threshold <= 0
                or not isinstance(triggered_at, str)
                or not triggered_at.strip()
            ):
                raise ValueError("last trigger time entry is invalid")
            if threshold in configured_thresholds:
                parsed_times[threshold] = triggered_at
        if parsed_times:
            result[symbol] = parsed_times
    return result


def _event(event: dict) -> AlertEvent:
    status = event["delivery_status"]
    if status not in {"pending", "queued", "sent", "failed", "not_configured"}:
        raise ValueError("event delivery status is invalid")
    failure_reason = event.get("failure_reason")
    last_attempt_at = event.get("last_attempt_at")
    if status == "failed":
        if not isinstance(last_attempt_at, str) or not last_attempt_at.strip():
            raise ValueError("failed event attempt time is missing")
        if failure_reason not in _SAFE_FAILURE_REASONS:
            failure_reason = "Telegram delivery failed"
    else:
        failure_reason = None
        if last_attempt_at is not None and not isinstance(last_attempt_at, str):
            raise ValueError("event attempt time is invalid")
    symbol = event["symbol"]
    signal = event["signal"]
    triggered_at = event["triggered_at"]
    event_id = event.get("event_id") or uuid4().hex
    event_type = event.get("event_type", "oi_scale")
    if (
        not _is_symbol(symbol)
        or not _is_non_empty_string(signal)
        or not _is_non_empty_string(triggered_at)
        or not _is_non_empty_string(event_id)
        or event_type not in {"oi_scale", "oi_expansion"}
    ):
        raise ValueError("event identity is invalid")
    oi_value = _positive_finite(event["oi_value"])
    threshold = _positive_finite(event["threshold"])
    return AlertEvent(
        symbol=symbol,
        oi_value=oi_value,
        threshold=threshold,
        signal=signal,
        triggered_at=triggered_at,
        event_id=event_id,
        event_type=event_type,
        oi_change_percent=_optional_finite(event.get("oi_change_percent")),
        price_change_percent=_optional_finite(event.get("price_change_percent")),
        explanation=(
            _optional_string(event.get("explanation"))
            or f"{signal}: total OI reached ${oi_value:,.0f}"
        ),
        exchange_timestamp_ms=_optional_positive_int(
            event.get("exchange_timestamp_ms")
        ),
        delivery_status=status,
        failure_reason=failure_reason,
        last_attempt_at=last_attempt_at,
    )


def _optional_finite(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("event metric is invalid")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("event metric is invalid") from exc
    if not isfinite(parsed):
        raise ValueError("event metric is invalid")
    return parsed


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("event explanation is invalid")
    return value


def _optional_positive_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("event exchange timestamp is invalid")
    parsed = int(value)
    if parsed != value or parsed <= 0 or parsed > 2**53 - 1:
        raise ValueError("event exchange timestamp is invalid")
    return parsed


def _validate_config_booleans(config: dict) -> None:
    for field in (
        "enabled",
        "scale_alerts_enabled",
        "require_cvd_confirmation",
    ):
        if field in config and not isinstance(config[field], bool):
            raise ValueError(f"{field} must be a boolean")


def _positive_finite(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("alert number is invalid")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("alert number is invalid") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError("alert number is invalid")
    return parsed


def _is_symbol(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[A-Z0-9]+USDT", value) is not None
    )


def _is_non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reject_json_constant(_value: str):
    raise ValueError("non-standard JSON number")
