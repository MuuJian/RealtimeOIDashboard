import json
import threading
import socket
import time
import unittest
from http.client import HTTPConnection

from realtime_oi_dashboard.application.background_service import (
    BackgroundPollerService,
    BackgroundServiceStopped,
)
from realtime_oi_dashboard.server import create_dashboard_server
from realtime_oi_dashboard.profile import resolve_profile


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
            "config": {
                "enabled": True,
                "thresholds": [75e6, 100e6, 150e6],
                "scale_alerts_enabled": True,
                "change_window_minutes": 15,
                "min_oi_change_percent": 3.0,
                "min_price_change_percent": 0.5,
                "require_cvd_confirmation": False,
                "cooldown_minutes": 30,
                "symbols": [],
            },
            "notifier": {
                "status": "not_configured",
                "last_error": None,
                "last_attempt_at": None,
            },
            "storage": {"status": "ok", "last_error": None},
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
    def test_connection_limit_rejects_excess_and_releases_closed_slots(self):
        self.server._request_slots = threading.BoundedSemaphore(2)
        clients = []
        try:
            for _ in range(2):
                client = socket.create_connection(self.server.server_address, timeout=1)
                clients.append(client)
                client.sendall(b"GET /livez HTTP/1.1\r\n")
            deadline = time.monotonic() + 1
            while self.server._request_slots._value and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(self.server._request_slots._value, 0)
            with socket.create_connection(self.server.server_address, timeout=1) as extra:
                self.assertEqual(extra.recv(1), b"")
        finally:
            for client in clients:
                client.close()
        deadline = time.monotonic() + 1
        while self.server._request_slots._value != 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.server._request_slots._value, 2)
        connection = HTTPConnection(*self.server.server_address, timeout=1)
        try:
            connection.request("GET", "/livez")
            self.assertEqual(connection.getresponse().status, 200)
        finally:
            connection.close()

    def test_header_and_body_drips_cannot_extend_total_connection_deadline(self):
        self.server.request_timeout_seconds = 0.15
        requests = (
            b"GET /livez HTTP/1.1\r\nX-Drip: ",
            b"PUT /api/oi-alerts/config HTTP/1.1\r\nHost: localhost\r\n"
            b"Content-Type: application/json\r\nContent-Length: 1000\r\n\r\n",
        )
        for request in requests:
            with self.subTest(request=request):
                with socket.create_connection(self.server.server_address, timeout=1) as client:
                    client.sendall(request)
                    started = time.monotonic()
                    for _ in range(30):
                        try:
                            client.sendall(b" ")
                        except OSError:
                            break
                        time.sleep(0.02)
                    try:
                        received = client.recv(1)
                    except ConnectionResetError:
                        received = b""
                    self.assertEqual(received, b"")
                    self.assertLess(time.monotonic() - started, 0.5)

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
        self.assertEqual(
            signal_payload,
            {**self.signal_provider.state, "feature_window_minutes": None},
        )

    def test_runtime_config_exposes_the_full_profile(self):
        connection = HTTPConnection(
            "127.0.0.1", self.server.server_address[1], timeout=5
        )
        try:
            connection.request("GET", "/runtime-config.js")
            response = connection.getresponse()
            body = response.read().decode("utf-8")
        finally:
            connection.close()

        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertIn('"profile":"full"', body)
        self.assertIn('"cvd":true', body)
        self.assertIn('dataset.cvdEnabled="true"', body)

    def test_stable_profile_exposes_only_oi_routes(self):
        stable_server = create_dashboard_server(
            "127.0.0.1",
            0,
            oi_state_provider=self.oi_provider,
            signal_scan_state_provider=self.signal_provider,
            oi_alert_provider=self.alert_provider,
            profile=resolve_profile("stable"),
        )
        thread = threading.Thread(target=stable_server.serve_forever, daemon=True)
        thread.start()
        try:
            statuses = {}
            for path, method in (
                ("/api/oi", "GET"),
                ("/api/signal-scan", "GET"),
                ("/api/oi-alerts", "GET"),
                ("/api/oi-alerts/config", "PUT"),
                ("/api/oi-alerts/test-message", "POST"),
            ):
                connection = HTTPConnection(
                    "127.0.0.1", stable_server.server_address[1], timeout=5
                )
                try:
                    headers = {"Content-Type": "application/json"}
                    body = b"{}" if method != "GET" else None
                    connection.request(method, path, body=body, headers=headers)
                    response = connection.getresponse()
                    statuses[path] = response.status
                    response.read()
                finally:
                    connection.close()
        finally:
            stable_server.shutdown()
            thread.join(timeout=5)
            stable_server.server_close()

        self.assertEqual(statuses["/api/oi"], 200)
        for path in (
            "/api/signal-scan",
            "/api/oi-alerts",
            "/api/oi-alerts/config",
            "/api/oi-alerts/test-message",
        ):
            self.assertEqual(statuses[path], 404)

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

    def test_alert_state_whitelists_storage_and_per_event_delivery_diagnostics(self):
        self.alert_provider.state["storage"] = {
            "status": "load_error",
            "last_error": "Saved OI alert state could not be loaded; defaults are active",
            "path": "C:/private/oi-alerts.json",
        }
        self.alert_provider.state["active"] = [{
            "symbol": "BTCUSDT",
            "event_type": "oi_scale",
            "oi_value": 80e6,
            "threshold": 75e6,
            "signal": "OI scale alert",
            "oi_change_percent": None,
            "price_change_percent": None,
            "explanation": "OI scale alert: total OI is $80,000,000",
            "as_of": "2026-08-17T10:00:00Z",
            "last_triggered_at": "2026-08-17T10:00:00Z",
            "token": "must-not-leak",
        }]
        self.alert_provider.state["events"] = [{
            "symbol": "BTCUSDT",
            "event_id": "event-1",
            "event_type": "oi_scale",
            "oi_value": 80e6,
            "threshold": 75e6,
            "signal": "OI scale alert",
            "oi_change_percent": None,
            "price_change_percent": None,
            "explanation": "OI scale alert: total OI reached $80,000,000",
            "exchange_timestamp_ms": 1_787_327_400_000,
            "triggered_at": "2026-08-17T10:00:00Z",
            "delivery_status": "failed",
            "failure_reason": "Telegram delivery failed",
            "last_attempt_at": "2026-08-17T10:00:03Z",
            "chat_id": "must-not-leak",
        }]

        status, payload = self.request_json("/api/oi-alerts")

        self.assertEqual(status, 200)
        self.assertEqual(payload["storage"]["status"], "load_error")
        self.assertEqual(
            payload["active"][0]["as_of"],
            "2026-08-17T10:00:00Z",
        )
        self.assertEqual(payload["active"][0]["threshold"], 75e6)
        self.assertEqual(payload["events"][0]["failure_reason"], "Telegram delivery failed")
        self.assertEqual(payload["events"][0]["last_attempt_at"], "2026-08-17T10:00:03Z")
        self.assertNotIn("private", json.dumps(payload).lower())
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
            [{
                "enabled": True,
                "thresholds": [75e6, 100e6, 150e6],
                "scale_alerts_enabled": True,
                "change_window_minutes": 15,
                "min_oi_change_percent": 3.0,
                "min_price_change_percent": 0.5,
                "require_cvd_confirmation": False,
                "cooldown_minutes": 30,
                "symbols": [],
            }],
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
