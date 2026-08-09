import json
import threading
import unittest
from http.client import HTTPConnection

from realtime_oi_dashboard.application.background_service import (
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


class DashboardServerTests(unittest.TestCase):
    def setUp(self):
        self.oi_provider = FakeStateProvider({"schema_version": 6, "rows": []})
        self.server = create_dashboard_server(
            "127.0.0.1",
            0,
            oi_state_provider=self.oi_provider,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request_json(self, path):
        connection = HTTPConnection(
            "127.0.0.1",
            self.server.server_address[1],
            timeout=5,
        )
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = None
            return response.status, payload
        finally:
            connection.close()

    def test_serves_injected_oi_state_provider(self):
        oi_status, oi_payload = self.request_json("/api/oi")

        self.assertEqual(oi_status, 200)
        self.assertEqual(oi_payload, self.oi_provider.state)

    def test_signal_scan_route_is_not_added_to_stable(self):
        status, _payload = self.request_json("/api/signal-scan")

        self.assertEqual(status, 404)

    def test_stopped_provider_preserves_existing_503_response(self):
        self.server.oi_state_provider = FakeStateProvider(
            error=BackgroundServiceStopped("OI poller stopped")
        )

        status, payload = self.request_json("/api/oi")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "OI poller stopped"})

    def test_missing_provider_preserves_unavailable_response(self):
        self.server.oi_state_provider = None

        status, payload = self.request_json("/api/oi")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "OI poller unavailable"})


if __name__ == "__main__":
    unittest.main()
