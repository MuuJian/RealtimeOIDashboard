import threading
import unittest

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


if __name__ == "__main__":
    unittest.main()
