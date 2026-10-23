import json
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from realtime_oi_dashboard.application.oi.poller import OIPoller
from realtime_oi_dashboard.application.oi.telegram_channel import Oi24hChannelService
from realtime_oi_dashboard.domain.oi.state import OiUpdate
from realtime_oi_dashboard.infrastructure.telegram.notifier import TelegramNotifier, _post_json
from realtime_oi_dashboard.infrastructure.telegram.settings import (
    TelegramChannelSettings,
    load_channel_settings,
)


def update(change, symbol="BTCUSDT"):
    return OiUpdate(symbol, {
        "oi24hChangePercent": change,
        "currentOiValue": 80_000_000,
    }, time.monotonic())


class TelegramChannelSettingsTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "telegram.json"

    def test_default_file_is_optional_and_credentials_are_not_configured(self):
        with patch(
            "realtime_oi_dashboard.infrastructure.telegram.settings.DEFAULT_CONFIG_PATH",
            self.path,
        ):
            settings = load_channel_settings(environ={})
        self.assertEqual(settings, TelegramChannelSettings())

    def test_file_supports_numeric_channel_id_and_environment_overrides_each_field(self):
        self.path.write_text(json.dumps({
            "bot_token": "file-secret", "channel_id": -100123, "enabled": True,
            "drop_threshold_percent": -60,
            "rise_threshold_percent": 150,
        }))
        settings = load_channel_settings(self.path, environ={})
        self.assertEqual(settings.channel_id, "-100123")
        self.assertEqual(settings.drop_threshold_percent, -60)
        self.assertEqual(settings.rise_threshold_percent, 150)
        settings = load_channel_settings(environ={
            "TELEGRAM_CONFIG_FILE": str(self.path),
            "TELEGRAM_BOT_TOKEN": " env-secret ",
            "TELEGRAM_CHANNEL_ID": " @target ",
            "TELEGRAM_CHANNEL_ENABLED": "false",
            "TELEGRAM_OI_24H_DROP_PERCENT": "-50",
            "TELEGRAM_OI_24H_RISE_PERCENT": "80",
        })
        self.assertEqual(settings.bot_token, "env-secret")
        self.assertEqual(settings.channel_id, "@target")
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.drop_threshold_percent, -50)
        self.assertEqual(settings.rise_threshold_percent, 80)
        self.assertNotIn("secret", repr(settings))

    def test_explicit_missing_or_malformed_config_fails_without_leaking_contents(self):
        with self.assertRaisesRegex(ValueError, "does not exist"):
            load_channel_settings(self.path, environ={})
        for raw in ('{"bot_token":"private-secret",', '[]'):
            self.path.write_text(raw)
            with self.assertRaises(ValueError) as error:
                load_channel_settings(self.path, environ={})
            self.assertNotIn("private-secret", str(error.exception))

    def test_invalid_switch_and_thresholds_fail(self):
        self.path.write_text("{}")
        for env in (
            {"TELEGRAM_CHANNEL_ENABLED": "maybe"},
            *({"TELEGRAM_OI_24H_DROP_PERCENT": value}
              for value in ("-100", "0", "50", "NaN", "-Infinity", "abc")),
            *({"TELEGRAM_OI_24H_RISE_PERCENT": value}
              for value in ("-100", "0", "NaN", "Infinity", "abc")),
        ):
            with self.subTest(env=env), self.assertRaises(ValueError):
                load_channel_settings(self.path, environ=env)

    def test_invalid_json_thresholds_fail(self):
        for name, values in (
            ("rise_threshold_percent", (None, True, -1, 0, "NaN")),
            ("drop_threshold_percent", (None, True, -100, 0, "NaN")),
        ):
            for value in values:
                self.path.write_text(json.dumps({name: value}))
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    load_channel_settings(self.path, environ={})


class TelegramChannelRuleTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.notifier = TelegramNotifier(
            "secret", "@channel", post_json=lambda url, body: self.calls.append(body)
        )
        self.addCleanup(self.notifier.stop, timeout=1)
        self.service = Oi24hChannelService(
            TelegramChannelSettings("secret", "@channel"),
            notifier_factory=lambda **_: self.notifier,
        )

    def observe(self, *changes):
        self.service.observe_updates([update(change) for change in changes])
        self.notifier.drain_for_test()

    def test_strict_boundaries_both_directions_and_recrossing(self):
        self.observe(100, -50, 0)
        self.assertEqual(self.calls, [])
        self.observe(100.01, 130, None, float("nan"), 140)
        self.assertEqual(len(self.calls), 1)
        self.assertIn("+100.01%", self.calls[0]["text"])
        self.assertIn("$80,000,000", self.calls[0]["text"])
        self.assertEqual(self.calls[0]["chat_id"], "@channel")
        self.observe(100, 101, -50, -50.01, -90)
        self.assertEqual(len(self.calls), 3)
        self.assertIn("-50.01%", self.calls[-1]["text"])
        self.observe(-50, -100)
        self.assertEqual(len(self.calls), 4)

    def test_invalid_values_do_not_send_or_reset_deduplication(self):
        self.observe(None, True, "120", float("inf"), float("-inf"), -101)
        self.assertEqual(self.calls, [])
        self.observe(120, None, -101, float("nan"), 121)
        self.assertEqual(len(self.calls), 1)

    def test_custom_thresholds_control_boundaries_recrossing_and_message(self):
        self.service = Oi24hChannelService(
            TelegramChannelSettings(
                "secret", "@channel",
                rise_threshold_percent=80, drop_threshold_percent=-30,
            ),
            notifier_factory=lambda **_: self.notifier,
        )
        self.observe(80, -30)
        self.assertEqual(self.calls, [])
        self.observe(80.01, 90, -30.01, -40)
        self.assertEqual(len(self.calls), 2)
        self.assertIn("涨幅超过 80%", self.calls[0]["text"])
        self.assertIn("跌幅超过 30%", self.calls[1]["text"])
        self.observe(-30, -31, 80, 81)
        self.assertEqual(len(self.calls), 4)

    def test_symbols_are_independent_and_delisted_symbols_are_forgotten(self):
        self.service.observe_updates([update(101), update(-60, "ETHUSDT")])
        self.notifier.drain_for_test()
        self.assertEqual(len(self.calls), 2)
        self.service.retain_symbols({"ETHUSDT"})
        self.service.observe_updates([update(101), update(-60, "ETHUSDT")])
        self.notifier.drain_for_test()
        self.assertEqual(len(self.calls), 3)

    def test_queue_rejection_is_retried_on_next_update(self):
        with patch.object(self.notifier, "send_message", return_value=False):
            self.observe(110)
        self.observe(111)
        self.assertEqual(len(self.calls), 1)

    def test_missing_credentials_and_disabled_settings_never_start_worker(self):
        for settings in (
            TelegramChannelSettings(),
            TelegramChannelSettings("secret", ""),
            TelegramChannelSettings("", "@channel"),
            TelegramChannelSettings("secret", "@channel", False),
        ):
            with self.subTest(settings=settings):
                service = Oi24hChannelService(settings)
                service.observe_updates([update(110), update(-60)])
                self.assertIsNone(service._notifier._thread)
                service.close()

    def test_stable_profile_with_disabled_legacy_alerts_still_pushes_and_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            poller = OIPoller(
                market_cap_file=Path(directory) / "market-caps.json",
                alert_service=None,
                telegram_channel_service=self.service,
            )
            self.addCleanup(poller.close)
            poller.symbol_refresher.symbols = ["BTCUSDT", "ETHUSDT"]
            poller.refresh_symbols_if_needed = lambda: None
            poller._reset_after_clock_discontinuity = lambda: False
            poller.get_market_snapshot = lambda: SimpleNamespace(
                tickers={}, funding_rates={}, market_caps={}
            )
            poller.update_symbols = lambda *args, **kwargs: [
                update(101), None, update(-51, "ETHUSDT")
            ]
            poller.update_batch()
            self.notifier.drain_for_test()
            self.assertEqual(len(self.calls), 2)
            self.assertTrue(poller.get_alert_state()["disabled"])
            poller.stop()
            poller.update_batch()
            self.assertEqual(len(self.calls), 2)
            poller.close()
            self.assertFalse(self.notifier._thread.is_alive())

    def test_telegram_api_rejection_is_not_treated_as_success(self):
        with patch(
            "realtime_oi_dashboard.infrastructure.telegram.notifier.urlopen",
            return_value=BytesIO(b'{"ok": false, "description": "private"}'),
        ), self.assertRaisesRegex(ValueError, "Telegram delivery failed"):
            _post_json("https://example.invalid", {})
