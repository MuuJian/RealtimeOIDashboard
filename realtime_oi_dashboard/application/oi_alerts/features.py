"""Build short-window OI features and directional expansion events."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite

from realtime_oi_dashboard.domain.oi_alerts.model import AlertConfig, AlertEvent


MINUTE_MS = 60_000
MAX_HISTORY_MINUTES = 4 * 60


@dataclass(frozen=True, slots=True)
class FeatureSample:
    timestamp_ms: int
    oi_quantity: float
    oi_value: float
    price: float
    cvd_ratio: float | None
    cvd_direction: str | None
    funding_rate_percent: float | None


@dataclass(frozen=True, slots=True)
class SignalFeature:
    symbol: str
    timestamp_ms: int
    window_minutes: int
    oi_quantity: float
    oi_value: float
    price: float
    oi_change_percent: float | None
    oi_value_change_percent: float | None
    price_change_percent: float | None
    cvd_ratio: float | None
    cvd_direction: str | None
    funding_rate_percent: float | None

    def to_payload(self) -> dict:
        return {
            "symbol": self.symbol,
            "as_of": _iso_timestamp(self.timestamp_ms),
            "exchange_timestamp_ms": self.timestamp_ms,
            "window_minutes": self.window_minutes,
            "current_oi": self.oi_quantity,
            "current_oi_value": self.oi_value,
            "price": self.price,
            "oi_change_percent": self.oi_change_percent,
            "oi_value_change_percent": self.oi_value_change_percent,
            "price_change_percent": self.price_change_percent,
            "cvd_ratio": self.cvd_ratio,
            "cvd_direction": self.cvd_direction,
            "funding_rate_percent": self.funding_rate_percent,
        }


class SignalFeatureTracker:
    """Keep a bounded in-memory history and publish comparable OI features."""

    def __init__(self) -> None:
        self._history: dict[str, deque[FeatureSample]] = {}
        self._features: dict[str, SignalFeature] = {}

    def observe(self, symbol: str, row: dict, *, window_minutes: int) -> SignalFeature | None:
        sample = _sample(row)
        if sample is None:
            return None
        history = self._history.setdefault(symbol, deque())
        if history and sample.timestamp_ms < history[-1].timestamp_ms:
            return self._features.get(symbol)
        if history and sample.timestamp_ms == history[-1].timestamp_ms:
            history[-1] = sample
        else:
            history.append(sample)
        cutoff = sample.timestamp_ms - MAX_HISTORY_MINUTES * MINUTE_MS
        while len(history) > 1 and history[1].timestamp_ms < cutoff:
            history.popleft()

        target = sample.timestamp_ms - window_minutes * MINUTE_MS
        baseline = None
        for candidate in reversed(history):
            if candidate.timestamp_ms <= target:
                baseline = candidate
                break
        feature = SignalFeature(
            symbol=symbol,
            timestamp_ms=sample.timestamp_ms,
            window_minutes=window_minutes,
            oi_quantity=sample.oi_quantity,
            oi_value=sample.oi_value,
            price=sample.price,
            oi_change_percent=_change(sample.oi_quantity, baseline.oi_quantity) if baseline else None,
            oi_value_change_percent=_change(sample.oi_value, baseline.oi_value) if baseline else None,
            price_change_percent=_change(sample.price, baseline.price) if baseline else None,
            cvd_ratio=sample.cvd_ratio,
            cvd_direction=sample.cvd_direction,
            funding_rate_percent=sample.funding_rate_percent,
        )
        self._features[symbol] = feature
        return feature

    def set_window(self, window_minutes: int) -> None:
        self._features = {}
        for symbol, history in self._history.items():
            if history:
                self.observe(symbol, _row_from_sample(history[-1]), window_minutes=window_minutes)

    def payload(self) -> dict[str, dict]:
        return {
            symbol: feature.to_payload()
            for symbol, feature in self._features.items()
        }

    def retain_symbols(self, symbols: set[str]) -> None:
        for mapping in (self._history, self._features):
            for symbol in set(mapping) - symbols:
                del mapping[symbol]


class ExpansionAlertEngine:
    """Emit one directional OI-expansion event per armed state."""

    def __init__(self) -> None:
        self._active: dict[str, str] = {}
        self._last_triggered_ms: dict[str, int] = {}

    def observe(self, feature: SignalFeature, config: AlertConfig) -> list[AlertEvent]:
        signal = classify_expansion(feature, config)
        if signal is None:
            if (
                feature.oi_change_percent is None
                or feature.oi_change_percent < config.min_oi_change_percent * 0.5
            ):
                self._active.pop(feature.symbol, None)
            return []
        previous = self._active.get(feature.symbol)
        self._active[feature.symbol] = signal
        if previous == signal or not config.enabled or not _monitors(config, feature.symbol):
            return []
        cooldown_ms = config.cooldown_minutes * MINUTE_MS
        last_triggered = self._last_triggered_ms.get(feature.symbol)
        if last_triggered is not None and feature.timestamp_ms - last_triggered < cooldown_ms:
            return []
        self._last_triggered_ms[feature.symbol] = feature.timestamp_ms
        return [
            AlertEvent(
                symbol=feature.symbol,
                oi_value=feature.oi_value,
                threshold=config.min_oi_change_percent,
                signal=signal,
                triggered_at=_iso_timestamp(feature.timestamp_ms),
                event_type="oi_expansion",
                oi_change_percent=feature.oi_change_percent,
                price_change_percent=feature.price_change_percent,
                explanation=explain_expansion(feature, signal),
                exchange_timestamp_ms=feature.timestamp_ms,
            )
        ]

    def reset(self) -> None:
        self._active.clear()

    def retain_symbols(self, symbols: set[str]) -> None:
        for mapping in (self._active, self._last_triggered_ms):
            for symbol in set(mapping) - symbols:
                del mapping[symbol]


def classify_expansion(feature: SignalFeature, config: AlertConfig) -> str | None:
    oi_change = feature.oi_change_percent
    price_change = feature.price_change_percent
    if oi_change is None or price_change is None or oi_change < config.min_oi_change_percent:
        return None
    cvd = feature.cvd_ratio
    cvd_available = cvd is not None and isfinite(cvd)
    if config.require_cvd_confirmation and not cvd_available:
        return None
    if price_change >= config.min_price_change_percent:
        if config.require_cvd_confirmation and cvd < 0:
            return "OI expansion"
        return "Bullish OI expansion"
    if price_change <= -config.min_price_change_percent:
        if config.require_cvd_confirmation and cvd > 0:
            return "OI expansion"
        return "Bearish OI expansion"
    return "OI expansion"


def explain_expansion(feature: SignalFeature, signal: str) -> str:
    parts = [
        f"OI {feature.window_minutes}m {feature.oi_change_percent:+.2f}%",
        f"price {feature.price_change_percent:+.2f}%",
    ]
    if feature.cvd_ratio is not None:
        parts.append(f"CVD {feature.cvd_ratio:+.1%}")
    if feature.funding_rate_percent is not None:
        parts.append(f"funding {feature.funding_rate_percent:+.4f}%")
    return f"{signal}: " + ", ".join(parts)


def active_feature_rows(features: dict[str, dict], config: AlertConfig) -> list[dict]:
    active = []
    for symbol, payload in features.items():
        try:
            feature = _feature_from_payload(symbol, payload)
        except (TypeError, ValueError):
            continue
        signal = classify_expansion(feature, config)
        if signal is None or not _monitors(config, symbol):
            continue
        row = feature.to_payload()
        row.update(
            {
                "event_type": "oi_expansion",
                "oi_value": feature.oi_value,
                "threshold": config.min_oi_change_percent,
                "signal": signal,
                "explanation": explain_expansion(feature, signal),
            }
        )
        active.append(row)
    return active


def _sample(row: dict) -> FeatureSample | None:
    timestamp_ms = _positive_int(row.get("oiUpdatedAt"))
    oi_quantity = _positive_float(row.get("currentOi"))
    oi_value = _positive_float(row.get("currentOiValue"))
    price = _positive_float(row.get("price"))
    if None in (timestamp_ms, oi_quantity, oi_value, price):
        return None
    return FeatureSample(
        timestamp_ms=timestamp_ms,
        oi_quantity=oi_quantity,
        oi_value=oi_value,
        price=price,
        cvd_ratio=_optional_float(row.get("cvd15mRatio")),
        cvd_direction=(
            _optional_text(row.get("cvdDirection"))
            or _optional_text(row.get("cvdStatus"))
        ),
        funding_rate_percent=_optional_float(row.get("fundingRatePercent")),
    )


def _row_from_sample(sample: FeatureSample) -> dict:
    return {
        "oiUpdatedAt": sample.timestamp_ms,
        "currentOi": sample.oi_quantity,
        "currentOiValue": sample.oi_value,
        "price": sample.price,
        "cvd15mRatio": sample.cvd_ratio,
        "cvdDirection": sample.cvd_direction,
        "fundingRatePercent": sample.funding_rate_percent,
    }


def _feature_from_payload(symbol: str, payload: dict) -> SignalFeature:
    return SignalFeature(
        symbol=symbol,
        timestamp_ms=int(payload["exchange_timestamp_ms"]),
        window_minutes=int(payload["window_minutes"]),
        oi_quantity=float(payload["current_oi"]),
        oi_value=float(payload["current_oi_value"]),
        price=float(payload["price"]),
        oi_change_percent=_optional_float(payload.get("oi_change_percent")),
        oi_value_change_percent=_optional_float(payload.get("oi_value_change_percent")),
        price_change_percent=_optional_float(payload.get("price_change_percent")),
        cvd_ratio=_optional_float(payload.get("cvd_ratio")),
        cvd_direction=_optional_text(payload.get("cvd_direction")),
        funding_rate_percent=_optional_float(payload.get("funding_rate_percent")),
    )


def _change(current: float, previous: float) -> float | None:
    if previous <= 0:
        return None
    value = (current / previous - 1) * 100
    return value if isfinite(value) else None


def _positive_float(value: object) -> float | None:
    parsed = _optional_float(value)
    return parsed if parsed is not None and parsed > 0 else None


def _optional_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if isfinite(parsed) else None


def _positive_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed > 0 else None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _monitors(config: AlertConfig, symbol: str) -> bool:
    return not config.symbols or symbol in config.symbols


def _iso_timestamp(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat(
        timespec="seconds"
    )
