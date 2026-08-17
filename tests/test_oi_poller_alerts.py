import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from realtime_oi_dashboard.application.oi.poller import OIPoller
from realtime_oi_dashboard.application.oi_alerts.service import OiAlertService
from realtime_oi_dashboard.domain.oi.state import OiUpdate
from realtime_oi_dashboard.domain.oi_alerts.model import AlertConfig
from realtime_oi_dashboard.infrastructure.storage.oi_alerts import (
    AlertSnapshot,
    AlertStateRepository,
)


class RecordingNotifier:
    def __init__(self, *, mark_delivery):
        self.mark_delivery = mark_delivery
        self.enqueued = []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self, timeout):
        self.stopped = True

    def enqueue(self, event):
        self.enqueued.append(event)

    def send_test_message(self):
        return True

    def get_status(self):
        return {"status": "configured", "last_error": None, "last_attempt_at": None}


class RecordingAlertService:
    def __init__(self):
        self.observed = []
        self.state_at_observation = None
        self.state_provider = None
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def observe_updates(self, updates, *, triggered_at):
        if self.state_provider is not None:
            self.state_at_observation = {
                symbol: dict(row)
                for symbol, row in self.state_provider().items()
            }
        self.observed.append((list(updates), triggered_at))
        return []

    def save(self):
        pass

    def close(self):
        self.closed = True

    def get_state(self, rows):
        return {"rows": rows}

    def update_config(self, payload, rows):
        return {"payload": payload, "rows": rows}

    def send_test_message(self):
        return {"queued": True}


class OiAlertServiceTests(unittest.TestCase):
    def test_observe_updates_uses_current_oi_value_skips_null_updates_and_enqueues_events(self):
        with tempfile.TemporaryDirectory() as directory:
            notifier = None

            def notifier_factory(*, mark_delivery):
                nonlocal notifier
                notifier = RecordingNotifier(mark_delivery=mark_delivery)
                return notifier

            service = OiAlertService(
                AlertStateRepository(Path(directory) / "oi-alerts.json"),
                notifier_factory=notifier_factory,
            )
            service.start()
            service.observe_updates(
                [
                    OiUpdate("BTCUSDT", {"currentOiValue": 70_000_000}, 1),
                    None,
                    OiUpdate("ETHUSDT", {"currentOiValue": None}, 1),
                ],
                triggered_at="t1",
            )

            events = service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 80_000_000}, 2)],
                triggered_at="t2",
            )

            self.assertEqual([(event.symbol, event.threshold) for event in events], [("BTCUSDT", 75_000_000)])
            self.assertEqual(notifier.enqueued, events)
            self.assertEqual(service.get_state({})["events"][0]["delivery_status"], "pending")

    def test_notifier_delivery_replaces_immutable_event_and_persists_it(self):
        with tempfile.TemporaryDirectory() as directory:
            notifier = None

            def notifier_factory(*, mark_delivery):
                nonlocal notifier
                notifier = RecordingNotifier(mark_delivery=mark_delivery)
                return notifier

            repository = AlertStateRepository(Path(directory) / "oi-alerts.json")
            service = OiAlertService(repository, notifier_factory=notifier_factory)
            service.start()
            service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 70_000_000}, 1)],
                triggered_at="t1",
            )
            events = service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 80_000_000}, 2)],
                triggered_at="t2",
            )

            notifier.mark_delivery(events[0], "sent", None)

            self.assertEqual(service.get_state({})["events"][0]["delivery_status"], "sent")
            self.assertEqual(repository.load().events[0].delivery_status, "sent")

    def test_loaded_crossings_are_restored_before_the_first_alert_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertStateRepository(Path(directory) / "oi-alerts.json")
            repository.save(
                AlertSnapshot(
                    config=AlertConfig(True, (50_000_000, 90_000_000, 120_000_000)),
                    crossed_thresholds={"BTCUSDT": {50_000_000}},
                )
            )
            service = OiAlertService(
                repository,
                notifier_factory=RecordingNotifier,
            )

            events = service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 95_000_000}, 1)],
                triggered_at="t1",
            )

            self.assertEqual([(event.threshold, event.signal) for event in events], [(90_000_000, "Add position")])


class OIPollerAlertIntegrationTests(unittest.TestCase):
    def create_poller(self, alert_service):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        poller = OIPoller(
            snapshot_file=Path(directory.name) / "latest_oi.json",
            market_cap_file=Path(directory.name) / "market-caps.json",
            alert_service=alert_service,
        )
        poller.symbol_refresher.symbols = ["BTCUSDT", "ETHUSDT"]
        poller.refresh_symbols_if_needed = lambda: None
        poller.get_market_snapshot = lambda: SimpleNamespace(
            tickers={}, funding_rates={}, market_caps={}
        )
        poller._reset_after_clock_discontinuity = lambda: False
        poller.save_state = lambda: None
        return poller

    def test_successful_state_updates_are_observed_after_application(self):
        alerts = RecordingAlertService()
        poller = self.create_poller(alerts)
        alerts.state_provider = lambda: poller.oi_state.rows
        measured_at = time.monotonic()
        results = [
            OiUpdate("BTCUSDT", {"currentOiValue": 80_000_000}, measured_at),
            None,
            OiUpdate("ETHUSDT", {"currentOiValue": None}, measured_at),
        ]
        poller.update_symbols = lambda *_args, **_kwargs: results

        poller.update_batch()

        self.assertTrue(alerts.started)
        self.assertEqual(poller.oi_state.rows["BTCUSDT"]["currentOiValue"], 80_000_000)
        self.assertEqual(
            alerts.state_at_observation,
            {
                "BTCUSDT": {"currentOiValue": 80_000_000},
                "ETHUSDT": {"currentOiValue": None},
            },
        )
        self.assertEqual(alerts.observed[0][0], results)

    def test_close_stops_alert_notifier_when_binance_close_fails(self):
        alerts = RecordingAlertService()
        poller = self.create_poller(alerts)
        poller.binance.close = lambda: (_ for _ in ()).throw(RuntimeError("Binance close failed"))

        with self.assertRaisesRegex(RuntimeError, "Binance close failed"):
            poller.close()

        self.assertTrue(alerts.closed)

    def test_public_alert_operations_delegate_to_the_alert_service(self):
        alerts = RecordingAlertService()
        poller = self.create_poller(alerts)
        poller.oi_state.rows["BTCUSDT"] = {"currentOiValue": 80_000_000}

        self.assertEqual(
            poller.get_alert_state(),
            {"rows": {"BTCUSDT": {"currentOiValue": 80_000_000}}},
        )
        self.assertEqual(
            poller.update_alert_config({"enabled": False}),
            {
                "payload": {"enabled": False},
                "rows": {"BTCUSDT": {"currentOiValue": 80_000_000}},
            },
        )
        self.assertEqual(poller.send_alert_test_message(), {"queued": True})


if __name__ == "__main__":
    unittest.main()
