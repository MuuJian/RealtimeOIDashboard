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
        self.provider = FakeStateProvider({"schema_version": 6, "rows": []})
        self.server = create_dashboard_server(
            "127.0.0.1",
            0,
            oi_state_provider=self.provider,
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
            payload = response.read()
            content_type = response.getheader("Content-Type", "")
            if content_type.startswith("application/json"):
                payload = json.loads(payload)
            return response.status, payload
        finally:
            connection.close()

    def test_serves_injected_oi_state_provider(self):
        status, payload = self.request_json("/api/oi")

        self.assertEqual(status, 200)
        self.assertEqual(payload, self.provider.state)

    def test_stopped_provider_preserves_existing_503_response(self):
        self.server.oi_state_provider = FakeStateProvider(
            error=BackgroundServiceStopped("OI poller stopped")
        )

        status, payload = self.request_json("/api/oi")

        self.assertEqual(status, 503)
        self.assertEqual(payload, {"error": "OI poller stopped"})

    def test_signal_scan_route_is_not_added_to_stable(self):
        status, _ = self.request_json("/api/signal-scan")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
