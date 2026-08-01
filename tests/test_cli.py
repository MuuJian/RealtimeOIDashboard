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


if __name__ == "__main__":
    unittest.main()
