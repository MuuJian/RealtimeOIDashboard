import threading
import unittest
from unittest.mock import patch

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.infrastructure.binance.weight_budget import (
    BinanceWeightBudget,
)
from realtime_oi_dashboard.infrastructure.http import JsonHttpClient


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"ok": True}


class FakeSession:
    def __init__(self):
        self.closed = False

    def get(self, _url, **_kwargs):
        return FakeResponse()

    def close(self):
        self.closed = True


class JsonHttpClientSessionLifecycleTests(unittest.TestCase):
    def create_client(self):
        sessions = []

        def session_factory():
            session = FakeSession()
            sessions.append(session)
            return session

        client = JsonHttpClient(
            session_factory=session_factory,
            before_request=None,
        )
        return client, sessions

    def test_short_lived_thread_sessions_do_not_accumulate(self):
        client, sessions = self.create_client()

        for _ in range(50):
            worker = threading.Thread(
                target=lambda: client.get_json("https://example.test/data")
            )
            worker.start()
            worker.join(timeout=2)
            self.assertFalse(worker.is_alive())

        self.assertEqual(len(sessions), 50)
        self.assertEqual(len(client._sessions), 1)
        self.assertEqual(sum(session.closed for session in sessions), 49)
        client.close()
        self.assertTrue(all(session.closed for session in sessions))

    def test_worker_can_release_its_session_immediately(self):
        client, sessions = self.create_client()

        def request_and_release():
            client.get_json("https://example.test/data")
            client.release_current_thread_session()

        worker = threading.Thread(target=request_and_release)
        worker.start()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(client._sessions), 0)
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0].closed)

    def test_default_weight_wait_uses_the_client_cancellation_path(self):
        stop_event = threading.Event()
        session_calls = []
        waits = []
        request_url = "https://fapi.binance.com/fapi/v1/time"
        budget = BinanceWeightBudget(
            weight_per_minute=1,
            monotonic=lambda: 0.0,
        )
        budget.acquire(request_url)

        def check_cancelled():
            if stop_event.is_set():
                raise PollingStopped()

        def wait(delay):
            waits.append(delay)
            stop_event.set()
            check_cancelled()

        def session_factory():
            session_calls.append(True)
            return FakeSession()

        with patch(
            "realtime_oi_dashboard.infrastructure.http."
            "GLOBAL_BINANCE_WEIGHT_BUDGET",
            budget,
        ):
            client = JsonHttpClient(
                session_factory=session_factory,
                sleep=wait,
                check_cancelled=check_cancelled,
            )
            with self.assertRaises(PollingStopped):
                client.get_json(request_url)

        self.assertEqual(waits, [1.0])
        self.assertEqual(session_calls, [])
        client.close()

    def test_custom_before_request_callback_remains_supported(self):
        callbacks = []
        client = JsonHttpClient(
            session_factory=FakeSession,
            before_request=callbacks.append,
        )

        payload = client.get_json("https://example.test/data")

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(callbacks, ["https://example.test/data"])
        client.close()


if __name__ == "__main__":
    unittest.main()
