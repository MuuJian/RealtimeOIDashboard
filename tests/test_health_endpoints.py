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
        self.state = state
        self.error = error
        self.calls = 0

    def get_state(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.state


class HealthEndpointTests(unittest.TestCase):
    def setUp(self):
        self.oi_provider = FakeStateProvider(_oi_state())
        self.signal_provider = FakeStateProvider(_signal_state())
        self.server = create_dashboard_server(
            "127.0.0.1",
            0,
            oi_state_provider=self.oi_provider,
            signal_scan_state_provider=self.signal_provider,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, method, path):
        connection = HTTPConnection(
            "127.0.0.1",
            self.server.server_address[1],
            timeout=5,
        )
        try:
            connection.request(method, path)
            response = connection.getresponse()
            body = response.read()
            return response.status, response.getheader("Content-Length"), body
        finally:
            connection.close()

    def request_json(self, path):
        status, _length, body = self.request("GET", path)
        return status, json.loads(body)

    def test_livez_does_not_touch_background_providers(self):
        self.oi_provider.error = RuntimeError("must not be called")
        self.signal_provider.error = RuntimeError("must not be called")

        status, payload = self.request_json("/livez")

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})
        self.assertEqual(self.oi_provider.calls, 0)
        self.assertEqual(self.signal_provider.calls, 0)

    def test_readyz_reports_small_component_summary(self):
        status, payload = self.request_json("/readyz")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            {
                "status": "ready",
                "components": {
                    "oi": {"status": "ready", "rows": 1},
                    "signalScan": {"status": "ready", "signals": 1},
                    "cvd": {"status": "ready", "health": "live"},
                },
            },
        )

    def test_empty_oi_rows_make_readyz_unavailable(self):
        self.oi_provider.state = _oi_state(rows=[])

        status, payload = self.request_json("/readyz")

        self.assertEqual(status, 503)
        self.assertEqual(payload["status"], "not_ready")
        self.assertEqual(
            payload["components"]["oi"],
            {"status": "warming", "rows": 0},
        )

    def test_stopped_or_failed_oi_provider_returns_503(self):
        for error, expected_status in (
            (BackgroundServiceStopped("stopped"), "stopped"),
            (RuntimeError("failed"), "error"),
        ):
            with self.subTest(expected_status=expected_status):
                self.oi_provider.error = error
                status, payload = self.request_json("/readyz")
                self.assertEqual(status, 503)
                self.assertEqual(
                    payload["components"]["oi"]["status"],
                    expected_status,
                )

    def test_optional_component_failure_does_not_block_readiness(self):
        self.signal_provider.error = BackgroundServiceStopped("stopped")
        self.oi_provider.state = _oi_state(cvd_health="stale")

        status, payload = self.request_json("/readyz")

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(
            payload["components"]["signalScan"]["status"],
            "stopped",
        )
        self.assertEqual(payload["components"]["cvd"]["status"], "degraded")

    def test_head_health_endpoints_return_headers_without_body(self):
        for path in ("/livez", "/readyz"):
            with self.subTest(path=path):
                status, content_length, body = self.request("HEAD", path)
                self.assertEqual(status, 200)
                self.assertGreater(int(content_length), 0)
                self.assertEqual(body, b"")


def _oi_state(*, rows=None, cvd_health="live"):
    return {
        "rows": [{"symbol": "BTCUSDT"}] if rows is None else rows,
        "error": None,
        "cvd_meta": {"serviceHealth": cvd_health},
    }


def _signal_state():
    return {
        "bulls": [{"symbol": "BTCUSDT"}],
        "bears": [],
        "spikes": [],
        "saved_at": "2026-08-11T12:00:00+08:00",
        "error": None,
        "partial": False,
    }


if __name__ == "__main__":
    unittest.main()
