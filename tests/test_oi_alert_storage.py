import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                delivery_status="failed",
                failure_reason="Telegram delivery failed",
                last_attempt_at=f"attempt{index}",
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
            self.assertEqual(loaded.events[0].failure_reason, "Telegram delivery failed")
            self.assertEqual(loaded.events[0].last_attempt_at, "attempt5")
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_malformed_json_returns_defaults_with_a_safe_load_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oi-alerts.json"
            path.write_text("{not json", encoding="utf-8")

            repository = AlertStateRepository(path)
            loaded = repository.load()

        self.assertEqual(loaded, AlertSnapshot.default())
        self.assertEqual(
            repository.load_error,
            "Saved OI alert state could not be loaded; defaults are active",
        )
        self.assertNotIn(str(path), repository.load_error)
        self.assertNotIn("not json", repository.load_error)

    def test_unreadable_state_returns_defaults_without_exposing_exception_details(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oi-alerts.json"
            path.write_text("{}", encoding="utf-8")
            repository = AlertStateRepository(path)

            with patch.object(
                Path,
                "read_text",
                side_effect=OSError("private path and credential-like detail"),
            ):
                loaded = repository.load()

        self.assertEqual(loaded, AlertSnapshot.default())
        self.assertEqual(
            repository.load_error,
            "Saved OI alert state could not be loaded; defaults are active",
        )
        self.assertNotIn("private path", repository.load_error)

    def test_structurally_corrupt_state_does_not_silently_drop_invalid_events(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oi-alerts.json"
            path.write_text(
                json.dumps({
                    "config": {
                        "enabled": True,
                        "thresholds": [75e6, 100e6, 150e6],
                    },
                    "crossed_thresholds": {},
                    "events": ["not an event"],
                }),
                encoding="utf-8",
            )
            repository = AlertStateRepository(path)

            loaded = repository.load()

        self.assertEqual(loaded, AlertSnapshot.default())
        self.assertEqual(
            repository.load_error,
            "Saved OI alert state could not be loaded; defaults are active",
        )

    def test_legacy_disabled_master_switch_keeps_both_alert_types_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oi-alerts.json"
            path.write_text(
                json.dumps({
                    "config": {
                        "enabled": False,
                        "thresholds": [75e6, 100e6, 150e6],
                    },
                    "crossed_thresholds": {},
                    "events": [],
                }),
                encoding="utf-8",
            )

            config = AlertStateRepository(path).load().config

        self.assertFalse(config.enabled)
        self.assertFalse(config.scale_alerts_enabled)
