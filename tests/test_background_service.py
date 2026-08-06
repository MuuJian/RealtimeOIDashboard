import unittest

from realtime_oi_dashboard.application.background_service import (
    BackgroundPollerService,
    BackgroundServiceStopped,
)


class FakePoller:
    def __init__(self):
        self.stopped = False
        self.closed = False
        self.state = {"value": 1}

    def run_forever(self):
        pass

    def get_state(self):
        return self.state

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeThread:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.alive = False
        self.join_timeouts = []

    def start(self):
        self.started = True
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.join_timeouts.append(timeout)
        self.alive = False


class BackgroundPollerServiceTests(unittest.TestCase):
    def create_service(self):
        poller = FakePoller()
        thread = None

        def thread_factory(**kwargs):
            nonlocal thread
            thread = FakeThread(**kwargs)
            return thread

        service = BackgroundPollerService(
            poller,
            thread_name="example-poller",
            stopped_message="example stopped",
            thread_factory=thread_factory,
        )
        return service, poller, thread

    def test_adapts_running_poller_to_state_provider(self):
        service, poller, thread = self.create_service()

        service.start()

        self.assertTrue(thread.started)
        self.assertEqual(thread.kwargs["target"], poller.run_forever)
        self.assertEqual(thread.kwargs["name"], "example-poller")
        self.assertTrue(thread.kwargs["daemon"])
        self.assertEqual(service.get_state(), {"value": 1})

    def test_rejects_state_reads_before_start_or_after_thread_exit(self):
        service, _, thread = self.create_service()

        with self.assertRaisesRegex(BackgroundServiceStopped, "example stopped"):
            service.get_state()

        service.start()
        thread.alive = False

        with self.assertRaisesRegex(BackgroundServiceStopped, "example stopped"):
            service.get_state()

    def test_stop_delegates_cancellation_and_join(self):
        service, poller, thread = self.create_service()
        service.start()

        stopped = service.stop(timeout=15)

        self.assertTrue(stopped)
        self.assertTrue(poller.stopped)
        self.assertEqual(thread.join_timeouts, [15])

    def test_close_releases_worker_resources(self):
        service, poller, _ = self.create_service()

        service.close()

        self.assertTrue(poller.closed)


if __name__ == "__main__":
    unittest.main()
