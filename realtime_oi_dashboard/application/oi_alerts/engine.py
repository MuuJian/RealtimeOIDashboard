from collections.abc import Mapping
from math import isfinite

from realtime_oi_dashboard.domain.oi_alerts.model import AlertConfig, AlertEvent, SIGNALS


class AlertEngine:
    """Tracks per-symbol upward crossings of configured OI thresholds."""

    def __init__(self, config: AlertConfig):
        self.config = config
        self.crossed_thresholds: dict[str, set[float]] = {}

    def observe(self, symbol: str, oi_value: float, triggered_at: str) -> list[AlertEvent]:
        if not isfinite(oi_value) or oi_value < 0:
            return []

        crossed = self.crossed_thresholds.get(symbol)
        if crossed is None:
            self.crossed_thresholds[symbol] = {
                threshold for threshold in self.config.thresholds if oi_value >= threshold
            }
            return []

        crossed.difference_update(
            threshold for threshold in self.config.thresholds if oi_value < threshold
        )
        if not self.config.enabled:
            return []

        events = []
        for threshold, signal in zip(self.config.thresholds, SIGNALS):
            if oi_value >= threshold and threshold not in crossed:
                crossed.add(threshold)
                events.append(
                    AlertEvent(symbol, oi_value, threshold, signal, triggered_at)
                )
        return events

    def baseline(self, rows: Mapping[str, float]) -> None:
        for symbol, oi_value in rows.items():
            if isfinite(oi_value) and oi_value >= 0:
                self.crossed_thresholds[symbol] = {
                    threshold
                    for threshold in self.config.thresholds
                    if oi_value >= threshold
                }

    def set_config(self, config: AlertConfig, rows: Mapping[str, float]) -> None:
        self.config = config
        self.crossed_thresholds = {}
        self.baseline(rows)
