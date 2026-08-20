import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from realtime_oi_dashboard import bootstrap
from realtime_oi_dashboard.application.background_service import BackgroundPollerService


class FakeArgs:
    host = "127.0.0.1"
    port = 0
    oi_batch_size = 10
    oi_batch_delay = 1
    oi_workers = 1


class FakeService:
    def __init__(self, *, should_fail_start=False):
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


class FakeSharedCache:
    def __init__(self):
        self.closed = False
        self.stopped = False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class RunDashboardTests(unittest.TestCase):
    def test_oi_start_failure_closes_service_without_serving(self):
        oi_service = FakeService(should_fail_start=True)
        server = FakeServer()

        with patch.object(
            bootstrap, "create_dashboard_server", return_value=server
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), oi_service)

        self.assertEqual(result, 1)
        self.assertEqual(server.serve_calls, 0)
        self.assertTrue(oi_service.closed)

    def test_bind_failure_closes_service(self):
        oi_service = FakeService()

        with patch.object(
            bootstrap,
            "create_dashboard_server",
            side_effect=OSError("address already in use"),
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), oi_service)

        self.assertEqual(result, 1)
        self.assertTrue(oi_service.closed)
        self.assertFalse(oi_service.started)

    def test_normal_shutdown_closes_the_shared_rest_cache(self):
        oi_service = FakeService()
        shared_cache = FakeSharedCache()

        with patch.object(
            bootstrap,
            "create_dashboard_server",
            return_value=FakeServer(),
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(
                FakeArgs(),
                oi_service,
                shared_cache,
            )

        self.assertEqual(result, 0)
        self.assertTrue(shared_cache.stopped)
        self.assertTrue(shared_cache.closed)


class MainTests(unittest.TestCase):
    def test_create_oi_service_returns_a_background_service(self):
        args = FakeArgs()
        args.oi_history_cache_seconds = 300
        args.funding_cache_seconds = 3600
        args.market_cap_cache_seconds = 3600

        service = bootstrap.create_oi_service(args)

        self.assertIsInstance(service, BackgroundPollerService)

    def test_main_passes_shared_cache_to_oi_service(self):
        args = FakeArgs()
        oi_service = FakeService()
        shared_cache = FakeSharedCache()

        with patch.object(bootstrap, "parse_args", return_value=args), patch.object(
            bootstrap, "create_shared_rest_cache", return_value=shared_cache
        ), patch.object(
            bootstrap, "create_oi_service", return_value=oi_service
        ) as create_oi_service, patch.object(
            bootstrap, "run_dashboard", return_value=0
        ) as run_dashboard:
            result = bootstrap.main([])

        self.assertEqual(result, 0)
        create_oi_service.assert_called_once_with(
            args,
            shared_rest_cache=shared_cache,
        )
        run_dashboard.assert_called_once_with(args, oi_service, shared_cache)


if __name__ == "__main__":
    unittest.main()
