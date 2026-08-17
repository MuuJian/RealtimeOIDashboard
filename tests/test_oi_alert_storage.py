import json
import tempfile
import unittest
from pathlib import Path

from realtime_oi_dashboard.domain.oi_alerts.model import AlertConfig, AlertEvent
from realtime_oi_dashboard.infrastructure.storage.oi_alerts import (
    AlertSnapshot,
    AlertStateRepository,
)


class AlertStateRepositoryTests(unittest.TestCase):
    def test_round_trips_config_crossed_state_and_newest_fifty_events(self):
        events = tuple(
            AlertEvent(
                symbol=f"TOKEN{index}USDT",
                oi_value=float(index),
                threshold=75_000_000,
                signal="Long entry",
                triggered_at=f"t{index}",
                delivery_status="sent",
            )
            for index in range(55)
        )
        snapshot = AlertSnapshot(
            config=AlertConfig(False, (80e6, 120e6, 180e6)),
            crossed_thresholds={"BTCUSDT": {80e6, 120e6}},
            events=events,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oi-alerts.json"
            repository = AlertStateRepository(path)
            repository.save(snapshot)

            loaded = repository.load()

            self.assertEqual(loaded.config, AlertConfig(False, (80e6, 120e6, 180e6)))
            self.assertEqual(loaded.crossed_thresholds, {"BTCUSDT": {80e6, 120e6}})
            self.assertEqual([event.triggered_at for event in loaded.events], [f"t{index}" for index in range(5, 55)])
            self.assertEqual(len(loaded.events), 50)
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_malformed_json_returns_an_empty_default_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oi-alerts.json"
            path.write_text("{not json", encoding="utf-8")

            loaded = AlertStateRepository(path).load()

        self.assertEqual(loaded, AlertSnapshot.default())
