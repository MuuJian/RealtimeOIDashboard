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
        self.signal_provider = FakeStateProvider(
            {"schema_version": 1, "bulls": [], "bears": [], "spikes": []}
        )
        self.server = create_dashboard_server(
            "127.0.0.1",
            0,
            oi_state_provider=self.oi_provider,
            signal_scan_state_provider=self.signal_provider,
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
            return response.status, json.loads(response.read())
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


if __name__ == "__main__":
    unittest.main()
