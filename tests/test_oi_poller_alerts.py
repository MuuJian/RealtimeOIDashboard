import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from realtime_oi_dashboard.application.oi.poller import OIPoller, ROW_MAX_AGE_SECONDS
from realtime_oi_dashboard.application.oi_alerts.service import OiAlertService
from realtime_oi_dashboard.domain.oi.state import OiUpdate
from realtime_oi_dashboard.domain.oi_alerts.model import AlertConfig, AlertEvent
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

    def test_notifier_delivery_replaces_immutable_event_and_persists_diagnostics(self):
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

            notifier.mark_delivery(
                events[0],
                "failed",
                "Telegram delivery failed",
                "2026-08-17T00:00:03+00:00",
            )

            event_payload = service.get_state({})["events"][0]
            self.assertEqual(event_payload["delivery_status"], "failed")
            self.assertEqual(event_payload["failure_reason"], "Telegram delivery failed")
            self.assertEqual(
                event_payload["last_attempt_at"], "2026-08-17T00:00:03+00:00"
            )
            self.assertEqual(repository.load().events[0].delivery_status, "failed")
            self.assertEqual(
                repository.load().events[0].last_attempt_at,
                "2026-08-17T00:00:03+00:00",
            )

    def test_restart_baselines_first_current_observation_instead_of_catching_up(self):
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

            self.assertEqual(events, [])
            later_events = service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 125_000_000}, 2)],
                triggered_at="t2",
            )
            self.assertEqual(
                [(event.threshold, event.signal) for event in later_events],
                [(120_000_000, "Very large OI alert")],
            )

    def test_runtime_history_is_bounded_to_the_newest_fifty_events(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OiAlertService(
                AlertStateRepository(Path(directory) / "oi-alerts.json"),
                notifier_factory=RecordingNotifier,
            )
            for index in range(55):
                symbol = f"TOKEN{index}USDT"
                service.observe_updates(
                    [OiUpdate(symbol, {"currentOiValue": 70_000_000}, index * 2)],
                    triggered_at=f"baseline-{index}",
                )
                service.observe_updates(
                    [OiUpdate(symbol, {"currentOiValue": 80_000_000}, index * 2 + 1)],
                    triggered_at=f"trigger-{index}",
                )

            snapshot = service._snapshot_unlocked()

            self.assertEqual(len(snapshot.events), 50)
            self.assertEqual(snapshot.events[0].symbol, "TOKEN5USDT")
            self.assertEqual(snapshot.events[-1].symbol, "TOKEN54USDT")

    def test_rearmed_symbol_churn_does_not_retain_trigger_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oi-alerts.json"
            repository = AlertStateRepository(path)
            service = OiAlertService(
                repository,
                notifier_factory=RecordingNotifier,
            )
            symbols = [f"TOKEN{index}USDT" for index in range(200)]

            service.observe_updates(
                [
                    OiUpdate(symbol, {"currentOiValue": 70_000_000}, 1)
                    for symbol in symbols
                ],
                triggered_at="baseline",
            )
            service.observe_updates(
                [
                    OiUpdate(symbol, {"currentOiValue": 80_000_000}, 2)
                    for symbol in symbols
                ],
                triggered_at="trigger",
            )
            service.observe_updates(
                [
                    OiUpdate(symbol, {"currentOiValue": 70_000_000}, 3)
                    for symbol in symbols
                ],
                triggered_at="rearm",
            )

            snapshot = service._snapshot_unlocked()
            persisted_payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual(len(snapshot.events), 50)
            self.assertEqual(snapshot.last_triggered_at, {})
            self.assertEqual(len(repository.load().events), 50)
            self.assertEqual(persisted_payload["last_triggered_at"], {})

    def test_active_alerts_include_the_latest_trigger_time_from_events(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OiAlertService(
                AlertStateRepository(Path(directory) / "oi-alerts.json"),
                notifier_factory=RecordingNotifier,
            )
            service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 70_000_000}, 1)],
                triggered_at="t1",
            )
            service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 80_000_000}, 2)],
                triggered_at="t2",
            )

            active = service.get_state(
                {"BTCUSDT": {"currentOiValue": 80_000_000}}
            )["active"]

            self.assertEqual(active[0]["last_triggered_at"], "t2")

    def test_active_scale_rows_follow_watchlist_and_use_exchange_time(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OiAlertService(
                AlertStateRepository(Path(directory) / "oi-alerts.json"),
                notifier_factory=RecordingNotifier,
            )
            service.update_config(
                {
                    "enabled": True,
                    "thresholds": [75e6, 100e6, 150e6],
                    "scale_alerts_enabled": True,
                    "change_window_minutes": 15,
                    "min_oi_change_percent": 3,
                    "min_price_change_percent": 0.5,
                    "require_cvd_confirmation": False,
                    "cooldown_minutes": 30,
                    "symbols": ["BTCUSDT"],
                },
                {},
            )
            exchange_ms = 1_787_327_400_000

            active = service.get_state({
                "BTCUSDT": {
                    "currentOiValue": 80_000_000,
                    "oiUpdatedAt": exchange_ms,
                },
                "ETHUSDT": {
                    "currentOiValue": 200_000_000,
                    "oiUpdatedAt": exchange_ms,
                },
            })["active"]

            self.assertEqual([row["symbol"] for row in active], ["BTCUSDT"])
            self.assertEqual(active[0]["exchange_timestamp_ms"], exchange_ms)
            self.assertEqual(active[0]["as_of"], "2026-08-21T15:50:00+00:00")

    def test_disabled_scale_rules_are_not_listed_as_active(self):
        with tempfile.TemporaryDirectory() as directory:
            service = OiAlertService(
                AlertStateRepository(Path(directory) / "oi-alerts.json"),
                notifier_factory=RecordingNotifier,
            )
            service.update_config(
                {
                    "enabled": True,
                    "thresholds": [75e6, 100e6, 150e6],
                    "scale_alerts_enabled": False,
                    "change_window_minutes": 15,
                    "min_oi_change_percent": 3,
                    "min_price_change_percent": 0.5,
                    "require_cvd_confirmation": False,
                    "cooldown_minutes": 30,
                    "symbols": [],
                },
                {},
            )

            active = service.get_state(
                {"BTCUSDT": {"currentOiValue": 80_000_000}}
            )["active"]

            self.assertEqual(active, [])

    def test_active_alert_keeps_trigger_time_after_event_eviction_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertStateRepository(Path(directory) / "oi-alerts.json")
            service = OiAlertService(
                repository,
                notifier_factory=RecordingNotifier,
            )
            service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 70_000_000}, 1)],
                triggered_at="btc-baseline",
            )
            service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 80_000_000}, 2)],
                triggered_at="btc-trigger",
            )
            for index in range(51):
                symbol = f"TOKEN{index}USDT"
                service.observe_updates(
                    [OiUpdate(symbol, {"currentOiValue": 70_000_000}, index * 2 + 3)],
                    triggered_at=f"baseline-{index}",
                )
                service.observe_updates(
                    [OiUpdate(symbol, {"currentOiValue": 80_000_000}, index * 2 + 4)],
                    triggered_at=f"trigger-{index}",
                )

            self.assertEqual(len(service.get_state({})["events"]), 50)
            self.assertNotIn(
                "BTCUSDT",
                {event["symbol"] for event in service.get_state({})["events"]},
            )

            restarted = OiAlertService(
                repository,
                notifier_factory=RecordingNotifier,
            )
            active = restarted.get_state(
                {"BTCUSDT": {"currentOiValue": 80_000_000}}
            )["active"]

            self.assertEqual(active[0]["last_triggered_at"], "btc-trigger")

    def test_corrupt_repository_state_is_exposed_as_a_safe_storage_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oi-alerts.json"
            path.write_text("{broken", encoding="utf-8")
            service = OiAlertService(
                AlertStateRepository(path),
                notifier_factory=RecordingNotifier,
            )

            storage = service.get_state({})["storage"]

            self.assertEqual(storage["status"], "load_error")
            self.assertEqual(
                storage["last_error"],
                "Saved OI alert state could not be loaded; defaults are active",
            )
            self.assertNotIn(str(path), str(storage))

    def test_uses_exchange_time_and_quantity_change_for_directional_event(self):
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
            start_ms = 1_787_327_400_000
            service.observe_updates(
                [OiUpdate("BTCUSDT", {
                    "currentOi": 100,
                    "currentOiValue": 50_000_000,
                    "price": 100,
                    "oiUpdatedAt": start_ms,
                }, 1)],
                triggered_at="server-time-1",
            )

            events = service.observe_updates(
                [OiUpdate("BTCUSDT", {
                    "currentOi": 104,
                    "currentOiValue": 52_520_000,
                    "price": 101,
                    "oiUpdatedAt": start_ms + 15 * 60_000,
                }, 2)],
                triggered_at="server-time-2",
            )

            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].signal, "Bullish OI expansion")
            self.assertAlmostEqual(events[0].oi_change_percent, 4.0)
            self.assertAlmostEqual(events[0].price_change_percent, 1.0)
            self.assertEqual(events[0].exchange_timestamp_ms, start_ms + 15 * 60_000)
            self.assertNotIn("server-time", events[0].triggered_at)
            self.assertEqual(notifier.enqueued, events)

    def test_unchanged_observation_does_not_rewrite_alert_state(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertStateRepository(Path(directory) / "oi-alerts.json")
            service = OiAlertService(
                repository,
                notifier_factory=RecordingNotifier,
            )
            service.observe_updates(
                [OiUpdate("BTCUSDT", {"currentOiValue": 70_000_000}, 1)],
                triggered_at="t1",
            )
            with patch.object(repository, "save", wraps=repository.save) as save:
                service.observe_updates(
                    [OiUpdate("BTCUSDT", {"currentOiValue": 71_000_000}, 2)],
                    triggered_at="t2",
                )

            save.assert_not_called()

    def test_start_requeues_persisted_pending_events_once(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = AlertStateRepository(Path(directory) / "oi-alerts.json")
            repository.save(AlertSnapshot(events=(
                AlertEvent(
                    "BTCUSDT", 80_000_000, 75_000_000,
                    "OI scale alert", "2026-08-22T00:00:00+00:00",
                ),
            )))
            notifier = None

            def notifier_factory(*, mark_delivery):
                nonlocal notifier
                notifier = RecordingNotifier(mark_delivery=mark_delivery)
                return notifier

            service = OiAlertService(repository, notifier_factory=notifier_factory)
            service.start()
            service.start()

            self.assertEqual(len(notifier.enqueued), 1)


class OIPollerAlertIntegrationTests(unittest.TestCase):
    def create_poller(self, alert_service, cvd_state_provider=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        poller = OIPoller(
            market_cap_file=Path(directory.name) / "market-caps.json",
            alert_service=alert_service,
            cvd_state_provider=cvd_state_provider,
        )
        poller.symbol_refresher.symbols = ["BTCUSDT", "ETHUSDT"]
        poller.refresh_symbols_if_needed = lambda: None
        poller.get_market_snapshot = lambda: SimpleNamespace(
            tickers={}, funding_rates={}, market_caps={}
        )
        poller._reset_after_clock_discontinuity = lambda: False
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
        self.assertEqual(alerts.observed[0][0], [results[0], results[2]])

    def test_alert_features_receive_the_matching_cvd_snapshot(self):
        alerts = RecordingAlertService()
        cvd = SimpleNamespace(get_state=lambda: {
            "rows": {
                "BTCUSDT": {
                    "cvd15mRatio": 0.25,
                    "cvdStatus": "buying",
                },
            },
        })
        poller = self.create_poller(alerts, cvd_state_provider=cvd)
        measured_at = time.monotonic()
        update = OiUpdate(
            "BTCUSDT",
            {"currentOiValue": 80_000_000},
            measured_at,
        )
        poller.update_symbols = lambda *_args, **_kwargs: [update]

        poller.update_batch()

        observed = alerts.observed[0][0][0]
        self.assertEqual(observed.row["cvd15mRatio"], 0.25)
        self.assertEqual(observed.row["cvdStatus"], "buying")

    def test_stale_updates_are_not_forwarded_to_alert_evaluation(self):
        alerts = RecordingAlertService()
        poller = self.create_poller(alerts)
        current_time = time.monotonic()
        stale = OiUpdate(
            "BTCUSDT",
            {"currentOiValue": 200_000_000},
            current_time - ROW_MAX_AGE_SECONDS - 1,
        )
        current = OiUpdate(
            "ETHUSDT",
            {"currentOiValue": 80_000_000},
            current_time,
        )
        poller.update_symbols = lambda *_args, **_kwargs: [stale, current]

        poller.update_batch()

        self.assertNotIn("BTCUSDT", poller.oi_state.rows)
        self.assertEqual(alerts.observed[0][0], [current])

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

    def test_explicit_none_disables_alerts_without_constructing_default_service(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "realtime_oi_dashboard.application.oi.poller."
            "_create_default_alert_service"
        ) as create_default_alert_service:
            poller = OIPoller(
                market_cap_file=Path(directory) / "market-caps.json",
                alert_service=None,
            )

        try:
            create_default_alert_service.assert_not_called()
            self.assertEqual(
                poller.alert_service.observe_updates([], triggered_at="t"),
                [],
            )
            self.assertEqual(poller.get_signal_features(), {})
            self.assertFalse(poller.send_alert_test_message())
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                poller.update_alert_config({"enabled": True})
        finally:
            poller.close()


if __name__ == "__main__":
    unittest.main()
