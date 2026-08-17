import json
import threading
import unittest
from http.client import HTTPConnection

from realtime_oi_dashboard.application.background_service import (
    BackgroundPollerService,
    BackgroundServiceStopped,
)
from realtime_oi_dashboard.server import create_dashboard_server


class FakeStateProvider:
    def __init__(self, state=None, error=None):
        self.state = {} if state is None else state
        self.error = error

    def get_state(self):
        if self.error is not None:
            raise self.error
        return self.state


class FakeAlertProvider:
    def __init__(self, state=None, error=None):
        self.state = {
            "config": {"enabled": True, "thresholds": [75e6, 100e6, 150e6]},
            "notifier": {
                "status": "not_configured",
                "last_error": None,
                "last_attempt_at": None,
            },
            "active": [],
            "events": [],
        }
        if state is not None:
            self.state = state
        self.error = error
        self.updated_payloads = []
        self.test_message_calls = 0

    def run_forever(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass

    def get_alert_state(self):
        if self.error is not None:
            raise self.error
        return self.state

    def update_alert_config(self, payload):
        if self.error is not None:
            raise self.error
        self.updated_payloads.append(payload)
        self.state["config"] = payload
        return self.state

    def send_alert_test_message(self):
        if self.error is not None:
            raise self.error
        self.test_message_calls += 1
        return {"queued": False, "notifier": self.state["notifier"]}


class DashboardServerTests(unittest.TestCase):
    def setUp(self):
        self.oi_provider = FakeStateProvider({"schema_version": 6, "rows": []})
        self.signal_provider = FakeStateProvider(
            {"schema_version": 1, "bulls": [], "bears": [], "spikes": []}
        )
        self.alert_provider = FakeAlertProvider()
        self.server = create_dashboard_server(
            "127.0.0.1",
            0,
            oi_state_provider=self.oi_provider,
            signal_scan_state_provider=self.signal_provider,
            oi_alert_provider=self.alert_provider,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request_json(
        self, path, *, method="GET", body=None, content_type="application/json"
    ):
        status, payload, _ = self.request_json_with_headers(
            path, method=method, body=body, content_type=content_type
        )
        return status, payload

    def request_json_with_headers(
        self, path, *, method="GET", body=None, content_type="application/json"
    ):
        connection = HTTPConnection(
            "127.0.0.1",
            self.server.server_address[1],
            timeout=5,
        )
        try:
            encoded_body = None
            headers = {}
            if body is not None:
                encoded_body = (
                    body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
                )
                headers["Content-Type"] = content_type
            connection.request(method, path, body=encoded_body, headers=headers)
            response = connection.getresponse()
            return (
                response.status,
                json.loads(response.read()),
                response.getheader("Cache-Control"),
            )
        finally:
            connection.close()

    def test_serves_both_injected_state_providers(self):
        oi_status, oi_payload = self.request_json("/api/oi")
        signal_status, signal_payload = self.request_json("/api/signal-scan")

        self.assertEqual(oi_status, 200)
        self.assertEqual(oi_payload, self.oi_provider.state)
        self.assertEqual(signal_status, 200)
        self.assertEqual(signal_payload, self.signal_provider.state)

    def test_stopped_provider_preserves_existing_503_response(self):
        self.server.signal_scan_state_provider = FakeStateProvider(
            error=BackgroundServiceStopped("Signal scan poller stopped")
        )

        status, payload = self.request_json("/api/signal-scan")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "Signal scan poller stopped"})

    def test_missing_optional_provider_preserves_unavailable_response(self):
        self.server.signal_scan_state_provider = None

        status, payload = self.request_json("/api/signal-scan")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "Signal scan poller unavailable"})

    def test_alert_state_is_safe_and_uses_the_public_telegram_shape(self):
        self.alert_provider.state["notifier"]["token"] = "must-not-leak"
        self.alert_provider.state["notifier"]["chat_id"] = "also-secret"

        status, payload = self.request_json("/api/oi-alerts")

        self.assertEqual(status, 200)
        self.assertEqual(payload["telegram"]["status"], "not_configured")
        self.assertEqual(payload["config"]["thresholds"], [75e6, 100e6, 150e6])
        self.assertNotIn("token", json.dumps(payload).lower())
        self.assertNotIn("chat_id", json.dumps(payload).lower())

    def test_alert_config_updates_only_validated_fields(self):
        status, payload, cache_control = self.request_json_with_headers(
            "/api/oi-alerts/config",
            method="PUT",
            body={
                "enabled": True,
                "thresholds": [75e6, 100e6, 150e6],
                "ignored": "client data",
            },
        )

        self.assertEqual(status, 200)
        self.assertEqual(cache_control, "no-store")
        self.assertEqual(payload["config"]["enabled"], True)
        self.assertEqual(
            self.alert_provider.updated_payloads,
            [{"enabled": True, "thresholds": [75e6, 100e6, 150e6]}],
        )

    def test_alert_config_rejects_non_increasing_thresholds(self):
        status, payload = self.request_json(
            "/api/oi-alerts/config",
            method="PUT",
            body={"enabled": True, "thresholds": [100e6, 75e6, 150e6]},
        )

        self.assertEqual(status, 400)
        self.assertIn("error", payload)
        self.assertEqual(self.alert_provider.updated_payloads, [])

    def test_alert_config_rejects_malformed_json(self):
        status, payload = self.request_json(
            "/api/oi-alerts/config",
            method="PUT",
            body=b'{"enabled":',
        )

        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_alert_config_rejects_non_json_and_oversized_bodies(self):
        status, payload = self.request_json(
            "/api/oi-alerts/config",
            method="PUT",
            body=b'{"enabled": true}',
            content_type="text/plain",
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

        status, payload = self.request_json(
            "/api/oi-alerts/config",
            method="PUT",
            body={
                "enabled": True,
                "thresholds": [75e6, 100e6, 150e6],
                "padding": "x" * (64 * 1024),
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_alert_routes_report_missing_provider_as_unavailable(self):
        self.server.oi_alert_provider = None

        status, payload = self.request_json("/api/oi-alerts")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "OI alert provider unavailable"})

    def test_alert_routes_report_a_stopped_provider_as_unavailable(self):
        self.server.oi_alert_provider = FakeAlertProvider(
            error=BackgroundServiceStopped("OI poller stopped")
        )

        status, payload = self.request_json("/api/oi-alerts")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "OI alert provider unavailable"})

    def test_alert_routes_use_the_background_service_liveness_boundary(self):
        self.server.oi_alert_provider = BackgroundPollerService(
            self.alert_provider,
            thread_name="oi-poller",
            stopped_message="OI poller stopped",
        )

        requests = (
            ("/api/oi-alerts", "GET", None),
            (
                "/api/oi-alerts/config",
                "PUT",
                {"enabled": True, "thresholds": [75e6, 100e6, 150e6]},
            ),
            ("/api/oi-alerts/test-message", "POST", {}),
        )
        for path, method, body in requests:
            with self.subTest(path=path):
                status, payload = self.request_json(path, method=method, body=body)
                self.assertEqual(status, 503)
                self.assertEqual(payload, {"error": "OI alert provider unavailable"})

        self.assertEqual(self.alert_provider.updated_payloads, [])
        self.assertEqual(self.alert_provider.test_message_calls, 0)

    def test_alert_config_rejects_non_standard_json_constants(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(constant=constant):
                status, payload = self.request_json(
                    "/api/oi-alerts/config",
                    method="PUT",
                    body=(
                        '{"enabled": true, "thresholds": [75000000, 100000000, '
                        '150000000], "ignored": '
                        + constant
                        + "}"
                    ).encode("utf-8"),
                )
                self.assertEqual(status, 400)
                self.assertIn("error", payload)

        self.assertEqual(self.alert_provider.updated_payloads, [])

    def test_alert_test_message_reports_unconfigured_without_calling_telegram(self):
        status, payload = self.request_json(
            "/api/oi-alerts/test-message", method="POST", body={}
        )

        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            {
                "queued": False,
                "telegram": {
                    "status": "not_configured",
                    "last_error": None,
                    "last_attempt_at": None,
                },
            },
        )
        self.assertEqual(self.alert_provider.test_message_calls, 1)


if __name__ == "__main__":
    unittest.main()
