from dataclasses import dataclass
from math import isfinite


SIGNALS = ("Long entry", "Add position", "High OI alert")


@dataclass(frozen=True, slots=True)
class AlertConfig:
    enabled: bool = True
    thresholds: tuple[float, float, float] = (75e6, 100e6, 150e6)

    @classmethod
    def default(cls) -> "AlertConfig":
        return cls()


@dataclass(frozen=True, slots=True)
class AlertEvent:
    symbol: str
    oi_value: float
    threshold: float
    signal: str
    triggered_at: str
    delivery_status: str = "pending"
    failure_reason: str | None = None
    last_attempt_at: str | None = None


def validate_alert_config(enabled: object, thresholds: object) -> AlertConfig:
    values = tuple(float(value) for value in thresholds)
    if len(values) != 3 or not all(isfinite(value) and value > 0 for value in values):
        raise ValueError("thresholds must contain three finite positive values")
    if not values[0] < values[1] < values[2]:
        raise ValueError("thresholds must be strictly increasing")
    return AlertConfig(bool(enabled), values)
