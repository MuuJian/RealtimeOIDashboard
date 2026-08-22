import unittest

from realtime_oi_dashboard.application.oi_alerts.features import (
    ExpansionAlertEngine,
    SignalFeature,
    SignalFeatureTracker,
    classify_expansion,
)
from realtime_oi_dashboard.domain.oi_alerts.model import AlertConfig


class SignalFeatureTrackerTests(unittest.TestCase):
    def test_uses_oi_quantity_and_exchange_window_for_change(self):
        tracker = SignalFeatureTracker()
        start_ms = 1_787_327_400_000
        tracker.observe(
            "BTCUSDT",
            {
                "currentOi": 100,
                "currentOiValue": 50_000,
                "price": 100,
                "oiUpdatedAt": start_ms,
            },
            window_minutes=15,
        )

        feature = tracker.observe(
            "BTCUSDT",
            {
                "currentOi": 104,
                "currentOiValue": 52_520,
                "price": 101,
                "oiUpdatedAt": start_ms + 15 * 60_000,
                "cvd15mRatio": 0.2,
            },
            window_minutes=15,
        )

        self.assertAlmostEqual(feature.oi_change_percent, 4.0)
        self.assertAlmostEqual(feature.oi_value_change_percent, 5.04)
        self.assertAlmostEqual(feature.price_change_percent, 1.0)
        self.assertEqual(feature.timestamp_ms, start_ms + 15 * 60_000)

    def test_out_of_order_sample_does_not_replace_latest_feature(self):
        tracker = SignalFeatureTracker()
        current = {
            "currentOi": 100,
            "currentOiValue": 50_000,
            "price": 100,
            "oiUpdatedAt": 2_000_000,
        }
        latest = tracker.observe("BTCUSDT", current, window_minutes=15)

        observed = tracker.observe(
            "BTCUSDT",
            {**current, "oiUpdatedAt": 1_000_000},
            window_minutes=15,
        )

        self.assertIs(observed, latest)
        self.assertEqual(tracker.payload()["BTCUSDT"]["exchange_timestamp_ms"], 2_000_000)


class ExpansionSignalTests(unittest.TestCase):
    def feature(self, **overrides):
        values = {
            "symbol": "BTCUSDT",
            "timestamp_ms": 2_000_000,
            "window_minutes": 15,
            "oi_quantity": 104,
            "oi_value": 52_520_000,
            "price": 101,
            "oi_change_percent": 4,
            "oi_value_change_percent": 5.04,
            "price_change_percent": 1,
            "cvd_ratio": 0.2,
            "cvd_direction": "buying",
            "funding_rate_percent": 0.01,
        }
        values.update(overrides)
        return SignalFeature(**values)

    def test_cvd_confirmation_blocks_missing_data_and_marks_disagreement(self):
        config = AlertConfig(require_cvd_confirmation=True)

        self.assertIsNone(classify_expansion(self.feature(cvd_ratio=None), config))
        self.assertEqual(
            classify_expansion(self.feature(cvd_ratio=-0.2), config),
            "OI expansion",
        )
        self.assertEqual(
            classify_expansion(self.feature(cvd_ratio=0.2), config),
            "Bullish OI expansion",
        )

    def test_active_signal_emits_only_once_until_it_rearms(self):
        engine = ExpansionAlertEngine()
        config = AlertConfig(cooldown_minutes=0)

        first = engine.observe(self.feature(), config)
        duplicate = engine.observe(
            self.feature(timestamp_ms=2_060_000, oi_change_percent=5),
            config,
        )
        engine.observe(
            self.feature(timestamp_ms=2_120_000, oi_change_percent=1),
            config,
        )
        rearmed = engine.observe(
            self.feature(timestamp_ms=2_180_000, oi_change_percent=4),
            config,
        )

        self.assertEqual(len(first), 1)
        self.assertEqual(duplicate, [])
        self.assertEqual(len(rearmed), 1)


if __name__ == "__main__":
    unittest.main()
