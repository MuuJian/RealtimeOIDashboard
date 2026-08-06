import threading
import unittest

from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.runtime import DashboardRuntime


class DashboardRuntimeTests(unittest.TestCase):
    def runtime(self, update_once, handle_error, *, workers=1):
        stop_event = threading.Event()
        closed = []

        def refresh_market_caps(_symbols_provider):
            stop_event.wait(1)

        runtime = DashboardRuntime(
            update_once,
            refresh_market_caps,
            lambda: {"BTCUSDT"},
            handle_error,
            lambda: closed.append(True),
            stop_event,
            batch_delay=0,
            workers=workers,
            timestamp=lambda: "now",
        )
        return runtime, stop_event, closed

    def test_runs_with_bounded_executor_and_closes_resources(self):
        executors = []

        def update_once(*, executor):
            executors.append(executor)
            runtime.stop_event.set()

        runtime, _, closed = self.runtime(
            update_once,
            lambda _error: None,
            workers=3,
        )

        runtime.run_forever()

        self.assertEqual(len(executors), 1)
        self.assertEqual(executors[0]._max_workers, 3)
        self.assertEqual(closed, [True])

    def test_batch_failure_is_delegated_before_next_iteration(self):
        errors = []

        def update_once(*, executor):
            raise ValueError("failed batch")

        def handle_error(error):
            errors.append(str(error))
            runtime.stop_event.set()

        runtime, _, closed = self.runtime(update_once, handle_error)

        runtime.run_forever()

        self.assertEqual(errors, ["failed batch"])
        self.assertEqual(closed, [True])

    def test_polling_stopped_exits_without_reporting_batch_error(self):
        errors = []
        runtime, _, closed = self.runtime(
            lambda **_kwargs: (_ for _ in ()).throw(PollingStopped()),
            errors.append,
        )

        runtime.run_forever()

        self.assertEqual(errors, [])
        self.assertEqual(closed, [True])

    def test_pre_stopped_runtime_skips_workers_but_still_closes(self):
        updates = []
        runtime, stop_event, closed = self.runtime(
            lambda **_kwargs: updates.append(True),
            lambda _error: None,
        )
        stop_event.set()

        runtime.run_forever()

        self.assertEqual(updates, [])
        self.assertEqual(closed, [True])


if __name__ == "__main__":
    unittest.main()
