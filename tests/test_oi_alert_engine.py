import unittest

from realtime_oi_dashboard.application.oi_alerts.engine import AlertEngine
from realtime_oi_dashboard.domain.oi_alerts.model import AlertConfig


class AlertEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AlertEngine(AlertConfig.default())

    def test_first_observation_baselines_without_event(self):
        self.assertEqual(self.engine.observe("BTCUSDT", 80_000_000, "t1"), [])

    def test_crossing_each_threshold_emits_the_fixed_signal(self):
        self.engine.observe("BTCUSDT", 70_000_000, "t1")
        events = self.engine.observe("BTCUSDT", 160_000_000, "t2")
        self.assertEqual(
            [(event.threshold, event.signal) for event in events],
            [
                (75_000_000, "Long entry"),
                (100_000_000, "Add position"),
                (150_000_000, "High OI alert"),
            ],
        )

    def test_staying_above_threshold_does_not_duplicate(self):
        self.engine.observe("ETHUSDT", 70_000_000, "t1")
        self.engine.observe("ETHUSDT", 80_000_000, "t2")
        self.assertEqual(self.engine.observe("ETHUSDT", 90_000_000, "t3"), [])

    def test_falling_below_then_recrossing_emits_again(self):
        self.engine.observe("SOLUSDT", 70_000_000, "t1")
        self.engine.observe("SOLUSDT", 110_000_000, "t2")
        self.engine.observe("SOLUSDT", 90_000_000, "t3")
        events = self.engine.observe("SOLUSDT", 110_000_000, "t4")
        self.assertEqual([event.threshold for event in events], [100_000_000])

    def test_save_configuration_rebaselines_without_catch_up(self):
        self.engine.baseline({"BTCUSDT": 200_000_000})
        self.engine.set_config(
            AlertConfig(True, (80e6, 120e6, 180e6)),
            {"BTCUSDT": 200_000_000},
        )
        self.assertEqual(self.engine.observe("BTCUSDT", 201_000_000, "t1"), [])
