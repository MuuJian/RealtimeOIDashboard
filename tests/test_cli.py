import io
import os
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from realtime_oi_dashboard.cli import parse_args


class ParseArgsTests(unittest.TestCase):
    def test_local_defaults_bind_only_to_loopback(self):
        with patch.dict(os.environ, {}, clear=True):
            args = parse_args([])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8777)
        self.assertEqual(args.market_cap_cache_seconds, 3_600)
        self.assertFalse(hasattr(args, "oi_history_cache_seconds"))

    def test_oi_history_cache_option_is_removed(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--oi-history-cache-seconds", "300"])

    def test_platform_port_enables_public_bind(self):
        with patch.dict(os.environ, {"PORT": "8080"}, clear=True):
            args = parse_args([])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 8080)

    def test_host_environment_variable_overrides_platform_default(self):
        with patch.dict(
            os.environ,
            {"HOST": "127.0.0.2", "PORT": "9000"},
            clear=True,
        ):
            args = parse_args([])

        self.assertEqual(args.host, "127.0.0.2")
        self.assertEqual(args.port, 9000)

    def test_command_line_values_override_environment(self):
        with patch.dict(os.environ, {"PORT": "8080"}, clear=True):
            args = parse_args(["--host", "localhost", "--port", "8877"])

        self.assertEqual(args.host, "localhost")
        self.assertEqual(args.port, 8877)

    def test_invalid_port_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--port", "65536"])

    def test_invalid_worker_count_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--oi-workers", "0"])

    def test_zero_ticker_cache_is_rejected(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--ticker-cache-seconds", "0"])

    def test_legacy_market_cap_option_remains_supported(self):
        args = parse_args(["--market-cap-cache-seconds", "7200"])

        self.assertEqual(args.market_cap_cache_seconds, 7200)

    def test_signal_scan_interval_has_a_default_and_is_validated(self):
        args = parse_args([])
        self.assertEqual(args.signal_scan_interval, 60)

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--signal-scan-interval", "0"])


if __name__ == "__main__":
    unittest.main()
