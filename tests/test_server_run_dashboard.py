import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from realtime_oi_dashboard import server as server_module


class FakeArgs:
    host = "127.0.0.1"
    port = 0  # ephemeral port so tests don't collide with anything real
    oi_batch_size = 10
    oi_batch_delay = 1
    oi_workers = 1


class FakeThread:
    """Stand-in for threading.Thread that can be told to fail on start()."""

    def __init__(self, should_fail_start=False):
        self.should_fail_start = should_fail_start
        self.started = False
        self.join_calls = []
        self._alive = False

    def start(self):
        if self.should_fail_start:
            raise RuntimeError("thread failed to start")
        self.started = True
        self._alive = True

    def join(self, timeout=None):
        self.join_calls.append(timeout)
        # Simulate the target function noticing stop() and exiting promptly.
        self._alive = False

    def is_alive(self):
        return self._alive


class FakePoller:
    def __init__(self):
        self.closed = False
        self.stopped = False
        self.saved_state = False

    def close(self):
        self.closed = True

    def stop(self):
        self.stopped = True

    def save_state(self, force=False):
        self.saved_state = True


class FakeSignalScanPoller:
    def __init__(self):
        self.closed = False
        self.stopped = False

    def close(self):
        self.closed = True

    def stop(self):
        self.stopped = True


class RunDashboardThreadStartFailureTests(unittest.TestCase):
    def test_oi_thread_start_failure_closes_pollers_without_joining_unstarted_thread(self):
        """If thread.start() itself raises, _stop_poller must not be called on
        the never-started OI thread (its .join() would raise RuntimeError).
        Both pollers' cleanup should still run and run_dashboard should
        return 1 cleanly."""
        poller = FakePoller()
        signal_scan_poller = FakeSignalScanPoller()
        oi_thread = FakeThread(should_fail_start=True)
        signal_thread = FakeThread(should_fail_start=False)

        with patch.object(
            server_module, "create_poller_thread", return_value=oi_thread
        ), patch.object(
            server_module, "create_signal_scan_thread", return_value=signal_thread
        ), redirect_stdout(io.StringIO()):
            result = server_module.run_dashboard(FakeArgs(), poller, signal_scan_poller)

        self.assertEqual(result, 1)

        # The OI thread never started, so it must never be joined.
        self.assertFalse(oi_thread.started)
        self.assertEqual(oi_thread.join_calls, [])

        # The signal-scan thread.start() should never even be attempted,
        # since thread.start() (OI) raised first.
        self.assertFalse(signal_thread.started)

        # Cleanup for the never-started OI thread goes through the plain
        # close path, not _stop_poller (which would try to join it).
        self.assertTrue(poller.closed)
        self.assertFalse(poller.stopped)
        self.assertFalse(poller.saved_state)

        # The signal scan poller's HTTP session must still be released.
        self.assertTrue(signal_scan_poller.closed)

    def test_signal_scan_thread_start_failure_stops_already_started_oi_thread(self):
        """If the OI thread started fine but the signal-scan thread's
        start() raises, the OI thread DID start, so _stop_poller (stop +
        join + save_state) is the correct cleanup path for it."""
        poller = FakePoller()
        signal_scan_poller = FakeSignalScanPoller()
        oi_thread = FakeThread(should_fail_start=False)
        signal_thread = FakeThread(should_fail_start=True)

        with patch.object(
            server_module, "create_poller_thread", return_value=oi_thread
        ), patch.object(
            server_module, "create_signal_scan_thread", return_value=signal_thread
        ), redirect_stdout(io.StringIO()):
            result = server_module.run_dashboard(FakeArgs(), poller, signal_scan_poller)

        self.assertEqual(result, 1)

        # The OI thread did start, and _stop_poller should have joined it.
        self.assertTrue(oi_thread.started)
        self.assertEqual(oi_thread.join_calls, [15])
        self.assertTrue(poller.stopped)
        self.assertTrue(poller.saved_state)
        self.assertFalse(poller.closed)  # _stop_poller path, not the close-only path

        # The signal-scan thread never actually started.
        self.assertFalse(signal_thread.started)
        self.assertTrue(signal_scan_poller.closed)


if __name__ == "__main__":
    unittest.main()
