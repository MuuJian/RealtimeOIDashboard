import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from realtime_oi_dashboard import bootstrap


class FakeArgs:
    host = "127.0.0.1"
    port = 0
    oi_batch_size = 10
    oi_batch_delay = 1
    oi_workers = 1


class FakeWorker:
    def __init__(self):
        self.saved_state = False

    def save_state(self, force=False):
        self.saved_state = force


class FakeService:
    def __init__(self, *, should_fail_start=False):
        self.worker = FakeWorker()
        self.should_fail_start = should_fail_start
        self.started = False
        self.closed = False
        self.stop_timeouts = []

    def start(self):
        if self.should_fail_start:
            raise RuntimeError("thread failed to start")
        self.started = True

    def stop(self, *, timeout):
        self.stop_timeouts.append(timeout)
        return True

    def close(self):
        self.closed = True


class FakeServer:
    def __init__(self):
        self.serve_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def serve_forever(self):
        self.serve_calls += 1


class RunDashboardTests(unittest.TestCase):
    def test_normal_run_starts_and_stops_oi_service(self):
        service = FakeService()
        server = FakeServer()

        with patch.object(
            bootstrap, "create_dashboard_server", return_value=server
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), service)

        self.assertEqual(result, 0)
        self.assertEqual(server.serve_calls, 1)
        self.assertTrue(service.started)
        self.assertEqual(
            service.stop_timeouts,
            [bootstrap.SHUTDOWN_TIMEOUT_SECONDS],
        )
        self.assertTrue(service.worker.saved_state)

    def test_start_failure_closes_service_without_serving(self):
        service = FakeService(should_fail_start=True)
        server = FakeServer()

        with patch.object(
            bootstrap, "create_dashboard_server", return_value=server
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), service)

        self.assertEqual(result, 1)
        self.assertEqual(server.serve_calls, 0)
        self.assertTrue(service.closed)

    def test_bind_failure_closes_service(self):
        service = FakeService()

        with patch.object(
            bootstrap,
            "create_dashboard_server",
            side_effect=OSError("address already in use"),
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), service)

        self.assertEqual(result, 1)
        self.assertTrue(service.closed)
        self.assertFalse(service.started)


if __name__ == "__main__":
    unittest.main()
