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
        self.signal_scan_state_provider = object()
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
    def test_run_dashboard_injects_checked_oi_service_as_alert_provider(self):
        oi_service = FakeService()
        signal_service = FakeService()
        server = FakeServer()

        with patch.object(
            bootstrap, "create_dashboard_server", return_value=server
        ) as create_dashboard_server, redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), oi_service, signal_service)

        self.assertEqual(result, 0)
        self.assertIs(
            create_dashboard_server.call_args.kwargs["oi_alert_provider"], oi_service
        )

    def test_oi_start_failure_closes_both_services_without_serving(self):
        oi_service = FakeService(should_fail_start=True)
        signal_service = FakeService()
        server = FakeServer()

        with patch.object(
            bootstrap, "create_dashboard_server", return_value=server
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), oi_service, signal_service)

        self.assertEqual(result, 1)
        self.assertEqual(server.serve_calls, 0)
        self.assertTrue(oi_service.closed)
        self.assertTrue(signal_service.closed)
        self.assertFalse(signal_service.started)

    def test_signal_scan_start_failure_keeps_oi_dashboard_running(self):
        oi_service = FakeService()
        signal_service = FakeService(should_fail_start=True)
        server = FakeServer()

        with patch.object(
            bootstrap, "create_dashboard_server", return_value=server
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), oi_service, signal_service)

        self.assertEqual(result, 0)
        self.assertEqual(server.serve_calls, 1)
        self.assertTrue(oi_service.started)
        self.assertEqual(
            oi_service.stop_timeouts,
            [bootstrap.SHUTDOWN_TIMEOUT_SECONDS],
        )
        self.assertTrue(oi_service.worker.saved_state)
        self.assertFalse(signal_service.started)
        self.assertTrue(signal_service.closed)
        self.assertIsNone(server.signal_scan_state_provider)

    def test_bind_failure_closes_both_services(self):
        oi_service = FakeService()
        signal_service = FakeService()

        with patch.object(
            bootstrap,
            "create_dashboard_server",
            side_effect=OSError("address already in use"),
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(FakeArgs(), oi_service, signal_service)

        self.assertEqual(result, 1)
        self.assertTrue(oi_service.closed)
        self.assertTrue(signal_service.closed)
        self.assertFalse(oi_service.started)
        self.assertFalse(signal_service.started)

    def test_normal_shutdown_closes_the_shared_rest_cache(self):
        oi_service = FakeService()
        signal_service = FakeService()
        shared_cache = FakeSharedCache()

        with patch.object(
            bootstrap,
            "create_dashboard_server",
            return_value=FakeServer(),
        ), redirect_stdout(io.StringIO()):
            result = bootstrap.run_dashboard(
                FakeArgs(),
                oi_service,
                signal_service,
                shared_rest_cache=shared_cache,
            )

        self.assertEqual(result, 0)
        self.assertTrue(shared_cache.stopped)
        self.assertTrue(shared_cache.closed)


class MainTests(unittest.TestCase):
    def test_create_oi_service_returns_a_background_service(self):
        args = FakeArgs()
        args.oi_history_cache_seconds = 300
        args.ticker_cache_seconds = 10
        args.funding_cache_seconds = 3600
        args.market_cap_cache_seconds = 3600
        args.snapshot_save_interval = 10

        service = bootstrap.create_oi_service(args)

        self.assertIsInstance(service, BackgroundPollerService)

    def test_create_oi_service_wires_the_alert_service_into_the_oi_worker(self):
        args = FakeArgs()
        args.oi_history_cache_seconds = 300
        args.ticker_cache_seconds = 10
        args.funding_cache_seconds = 3600
        args.market_cap_cache_seconds = 3600
        args.snapshot_save_interval = 10
        captured = {}
        alert_service = object()

        class CapturingPoller:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def run_forever(self):
                pass

        with patch.object(
            bootstrap,
            "create_oi_alert_service",
            return_value=alert_service,
        ), patch.object(bootstrap, "OIPoller", CapturingPoller):
            service = bootstrap.create_oi_service(args)

        self.assertIsInstance(service, BackgroundPollerService)
        self.assertIs(captured["alert_service"], alert_service)

    def test_main_passes_optional_cvd_service_to_oi_service(self):
        args = FakeArgs()
        cvd_service = FakeService()
        oi_service = FakeService()
        signal_service = FakeService()
        shared_cache = FakeSharedCache()

        with patch.object(bootstrap, "parse_args", return_value=args), patch.object(
            bootstrap, "create_shared_rest_cache", return_value=shared_cache
        ), patch.object(
            bootstrap, "create_cvd_service", return_value=cvd_service
        ), patch.object(
            bootstrap, "create_oi_service", return_value=oi_service
        ) as create_oi_service, patch.object(
            bootstrap, "create_signal_scan_service", return_value=signal_service
        ), patch.object(bootstrap, "run_dashboard", return_value=0) as run_dashboard:
            result = bootstrap.main([])

        self.assertEqual(result, 0)
        create_oi_service.assert_called_once_with(
            args,
            cvd_state_provider=cvd_service,
            shared_rest_cache=shared_cache,
        )
        run_dashboard.assert_called_once_with(
            args,
            oi_service,
            signal_service,
            cvd_service,
            shared_cache,
        )

    def test_signal_scan_creation_failure_still_runs_oi_dashboard(self):
        args = FakeArgs()
        oi_service = FakeService()
        shared_cache = FakeSharedCache()

        with patch.object(bootstrap, "parse_args", return_value=args), patch.object(
            bootstrap, "create_shared_rest_cache", return_value=shared_cache
        ), patch.object(
            bootstrap, "create_cvd_service", side_effect=RuntimeError("CVD failed")
        ), patch.object(
            bootstrap, "create_oi_service", return_value=oi_service
        ), patch.object(
            bootstrap,
            "create_signal_scan_service",
            side_effect=RuntimeError("signal scanner creation failed"),
        ), patch.object(
            bootstrap, "run_dashboard", return_value=0
        ) as run_dashboard, redirect_stdout(io.StringIO()):
            result = bootstrap.main([])

        self.assertEqual(result, 0)
        run_dashboard.assert_called_once_with(
            args,
            oi_service,
            None,
            None,
            shared_cache,
        )


if __name__ == "__main__":
    unittest.main()
