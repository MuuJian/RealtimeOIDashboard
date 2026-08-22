import unittest

from realtime_oi_dashboard.server import _enrich_signal_scan_state


class FeatureProvider:
    def get_signal_features(self):
        return {
            "BTCUSDT": {
                "window_minutes": 15,
                "oi_change_percent": 4.2,
                "oi_value_change_percent": 5.1,
                "price_change_percent": 0.9,
                "current_oi_value": 125_000_000,
                "cvd_ratio": 0.12,
                "cvd_direction": "buying",
                "funding_rate_percent": 0.01,
                "exchange_timestamp_ms": 1_787_327_400_000,
            }
        }


class SignalScanEnrichmentTests(unittest.TestCase):
    def test_merges_oi_cvd_funding_and_explanation_into_scan_rows(self):
        row = {
            "symbol": "BTCUSDT",
            "price": 100.0,
            "chg1h": 1.0,
            "chg24h": 2.0,
            "aboveE20": 0.5,
            "isBull": True,
            "isBear": False,
            "volRatio": 1.2,
        }

        state = _enrich_signal_scan_state(
            {"bulls": [row], "bears": [], "spikes": []},
            FeatureProvider(),
        )

        enriched = state["bulls"][0]
        self.assertEqual(state["feature_window_minutes"], 15)
        self.assertEqual(enriched["oiChangePercent"], 4.2)
        self.assertEqual(enriched["cvd15mRatio"], 0.12)
        self.assertEqual(enriched["fundingRatePercent"], 0.01)
        self.assertIn("多頭趨勢", enriched["signalReason"])
        self.assertIn("OI +4.20%", enriched["signalReason"])

    def test_missing_feature_provider_keeps_scan_available(self):
        state = _enrich_signal_scan_state(
            {
                "bulls": [{
                    "symbol": "BTCUSDT",
                    "price": 100.0,
                    "chg1h": 1.0,
                    "chg24h": 2.0,
                    "aboveE20": 0.5,
                    "isBull": True,
                    "isBear": False,
                    "volRatio": 1.2,
                }],
                "bears": [],
                "spikes": [],
            },
            None,
        )

        self.assertIsNone(state["feature_window_minutes"])
        self.assertIn("OI 窗口預熱中", state["bulls"][0]["signalReason"])


if __name__ == "__main__":
    unittest.main()
