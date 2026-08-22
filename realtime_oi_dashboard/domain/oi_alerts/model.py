from dataclasses import dataclass, field
from math import isfinite
from uuid import uuid4


SIGNALS = ("OI scale alert", "Large OI alert", "Very large OI alert")
EXPANSION_SIGNALS = (
    "Bullish OI expansion",
    "Bearish OI expansion",
    "OI expansion",
)


@dataclass(frozen=True, slots=True)
class AlertConfig:
    enabled: bool = True
    thresholds: tuple[float, float, float] = (75e6, 100e6, 150e6)
    scale_alerts_enabled: bool = True
    change_window_minutes: int = 15
    min_oi_change_percent: float = 3.0
    min_price_change_percent: float = 0.5
    require_cvd_confirmation: bool = False
    cooldown_minutes: int = 30
    symbols: tuple[str, ...] = ()

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
    event_id: str = field(default_factory=lambda: uuid4().hex)
    event_type: str = "oi_scale"
    oi_change_percent: float | None = None
    price_change_percent: float | None = None
    explanation: str | None = None
    exchange_timestamp_ms: int | None = None
    delivery_status: str = "pending"
    failure_reason: str | None = None
    last_attempt_at: str | None = None


def validate_alert_config(
    enabled: object,
    thresholds: object,
    *,
    scale_alerts_enabled: object = True,
    change_window_minutes: object = 15,
    min_oi_change_percent: object = 3.0,
    min_price_change_percent: object = 0.5,
    require_cvd_confirmation: object = False,
    cooldown_minutes: object = 30,
    symbols: object = (),
) -> AlertConfig:
    values = tuple(float(value) for value in thresholds)
    if len(values) != 3 or not all(isfinite(value) and value > 0 for value in values):
        raise ValueError("thresholds must contain three finite positive values")
    if not values[0] < values[1] < values[2]:
        raise ValueError("thresholds must be strictly increasing")
    window = _bounded_int(
        "change_window_minutes", change_window_minutes, minimum=1, maximum=240
    )
    cooldown = _bounded_int(
        "cooldown_minutes", cooldown_minutes, minimum=0, maximum=1440
    )
    oi_change = _bounded_float(
        "min_oi_change_percent", min_oi_change_percent, minimum=0.01, maximum=1000
    )
    price_change = _bounded_float(
        "min_price_change_percent",
        min_price_change_percent,
        minimum=0,
        maximum=100,
    )
    normalized_symbols = _symbols(symbols)
    return AlertConfig(
        enabled=bool(enabled),
        thresholds=values,
        scale_alerts_enabled=bool(scale_alerts_enabled),
        change_window_minutes=window,
        min_oi_change_percent=oi_change,
        min_price_change_percent=price_change,
        require_cvd_confirmation=bool(require_cvd_confirmation),
        cooldown_minutes=cooldown,
        symbols=normalized_symbols,
    )


def _bounded_int(name: str, value: object, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed != value or parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} is outside the supported range")
    return parsed


def _bounded_float(
    name: str,
    value: object,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not isfinite(parsed) or parsed < minimum or parsed > maximum:
        raise ValueError(f"{name} is outside the supported range")
    return parsed


def _symbols(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("symbols must be a list")
    result = []
    seen = set()
    for raw_symbol in value:
        if not isinstance(raw_symbol, str):
            raise ValueError("symbols must contain strings")
        symbol = raw_symbol.strip().upper()
        if (
            not symbol.endswith("USDT")
            or not symbol[:-4].isalnum()
            or symbol in seen
        ):
            if symbol in seen:
                continue
            raise ValueError("symbols must contain Binance USDT symbols")
        seen.add(symbol)
        result.append(symbol)
    if len(result) > 200:
        raise ValueError("symbols exceeds the supported limit")
    return tuple(result)
