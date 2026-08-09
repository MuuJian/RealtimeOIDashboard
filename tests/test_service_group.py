import unittest

from realtime_oi_dashboard.shared.runtime.services import ServiceGroup


class FakeService:
    def __init__(self, *, stop_result=True, close_error=None):
        self.started = False
        self.stop_result = stop_result
        self.stop_timeouts = []
        self.close_error = close_error
        self.closed = False

    def start(self):
        self.started = True

    def stop(self, *, timeout):
        self.stop_timeouts.append(timeout)
        return self.stop_result

    def close(self):
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class ServiceGroupTests(unittest.TestCase):
    def test_ignores_absent_optional_services(self):
        service = FakeService()
        group = ServiceGroup(required=("required", service), optional=("optional", None))

        group.start("required")
        result = group.stop("required", timeout=15)

        self.assertTrue(service.started)
        self.assertTrue(result.stopped)
        self.assertEqual(service.stop_timeouts, [15])
        self.assertIsNone(group.stop("optional", timeout=15))

    def test_reports_close_failures_without_skipping_other_services(self):
        failed = FakeService(close_error=RuntimeError("close failed"))
        healthy = FakeService()
        group = ServiceGroup(first=("first", failed), second=("second", healthy))

        failures = group.close_all()

        self.assertTrue(failed.closed)
        self.assertTrue(healthy.closed)
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0].key, "first")
        self.assertEqual(str(failures[0].error), "close failed")


if __name__ == "__main__":
    unittest.main()
