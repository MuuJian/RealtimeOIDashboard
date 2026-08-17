import unittest

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
