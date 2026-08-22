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
        if (
            not self.config.scale_alerts_enabled
            or not self._monitors(symbol)
        ):
            return []

        newly_crossed = [
            (threshold, signal)
            for threshold, signal in zip(self.config.thresholds, SIGNALS)
            if oi_value >= threshold and threshold not in crossed
        ]
        crossed.update(threshold for threshold, _signal in newly_crossed)
        if not newly_crossed:
            return []
        threshold, signal = newly_crossed[-1]
        return [AlertEvent(symbol, oi_value, threshold, signal, triggered_at)]

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

    def retain_symbols(self, symbols: set[str]) -> None:
        for symbol in set(self.crossed_thresholds) - symbols:
            del self.crossed_thresholds[symbol]

    def _monitors(self, symbol: str) -> bool:
        return not self.config.symbols or symbol in self.config.symbols
