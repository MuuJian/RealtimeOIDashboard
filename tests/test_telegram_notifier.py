import unittest
import queue

from realtime_oi_dashboard.domain.oi_alerts.model import AlertEvent
from realtime_oi_dashboard.infrastructure.telegram.notifier import TelegramNotifier


def alert_event():
    return AlertEvent(
        symbol="BTCUSDT",
        oi_value=80_000_000,
        threshold=75_000_000,
        signal="Long entry",
        triggered_at="2026-08-17T00:00:00Z",
    )


class TelegramNotifierTests(unittest.TestCase):
    def tearDown(self):
        for notifier in getattr(self, "notifiers", []):
            notifier.stop(timeout=1)

    def test_test_message_posts_to_token_endpoint_without_exposing_token(self):
        calls = []
        notifier = TelegramNotifier("secret", "123", post_json=lambda url, body: calls.append((url, body)))
        self.notifiers = [notifier]

        notifier.send_test_message()
        notifier.drain_for_test()

        self.assertEqual(calls[0][0], "https://api.telegram.org/botsecret/sendMessage")
        self.assertEqual(calls[0][1]["chat_id"], "123")
        self.assertNotIn("secret", notifier.get_status())

    def test_missing_credentials_reports_not_configured_and_never_posts(self):
        notifier = TelegramNotifier(None, None, post_json=lambda *_: self.fail("must not post"))
        self.notifiers = [notifier]

        self.assertEqual(notifier.get_status()["status"], "not_configured")
        notifier.enqueue(alert_event())

    def test_retries_twice_then_reports_sent_through_callback(self):
        attempts = []
        outcomes = []

        def post_json(url, body):
            attempts.append((url, body))
            if len(attempts) < 3:
                raise OSError("network down")

        notifier = TelegramNotifier(
            "secret",
            "123",
            post_json=post_json,
            mark_delivery=lambda event, status, error: outcomes.append((event, status, error)),
            sleep=lambda _: None,
        )
        self.notifiers = [notifier]

        event = alert_event()
        notifier.enqueue(event)
        notifier.drain_for_test()

        self.assertEqual(len(attempts), 3)
        self.assertEqual(outcomes, [(event, "sent", None)])
        self.assertEqual(event.delivery_status, "pending")

    def test_transport_error_does_not_expose_credentials_in_status_or_callback(self):
        outcomes = []

        def post_json(url, body):
            raise OSError("failed request https://api.telegram.org/botsecret/sendMessage for chat 123")

        notifier = TelegramNotifier(
            "secret",
            "123",
            post_json=post_json,
            mark_delivery=lambda event, status, error: outcomes.append((status, error)),
            sleep=lambda _: None,
        )
        self.notifiers = [notifier]

        notifier.enqueue(alert_event())
        notifier.drain_for_test()

        self.assertEqual(outcomes[0][0], "failed")
        self.assertNotIn("secret", str(notifier.get_status()))
        self.assertNotIn("123", str(notifier.get_status()))
        self.assertNotIn("secret", outcomes[0][1])
        self.assertNotIn("123", outcomes[0][1])

    def test_saturated_alert_queue_marks_event_and_public_status_failed(self):
        outcomes = []
        notifier = TelegramNotifier(
            "secret",
            "123",
            post_json=lambda *_: self.fail("must not post"),
            mark_delivery=lambda event, status, error: outcomes.append((event, status, error)),
        )
        self.notifiers = [notifier]
        notifier.start = lambda: None
        notifier._queue = queue.Queue(maxsize=100)
        for _ in range(100):
            notifier._queue.put_nowait((None, "queued"))

        event = alert_event()
        notifier.enqueue(event)

        self.assertEqual(outcomes, [(event, "failed", "delivery queue is full")])
        self.assertEqual(
            notifier.get_status(),
            {"status": "failed", "last_error": "delivery queue is full", "last_attempt_at": None},
        )
