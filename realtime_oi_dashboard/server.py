"""Local HTTP server and command-line entry for the realtime OI dashboard."""

from __future__ import annotations

import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from realtime_oi_dashboard.cli import parse_args
from realtime_oi_dashboard.application.poller import OIPoller, timestamp
from realtime_oi_dashboard.application.signal_scan import SignalScanPoller
from realtime_oi_dashboard.web import DashboardRequestHandler


ROOT_DIR = Path(__file__).resolve().parent
INDEX_FILE = ROOT_DIR / "index.html"
STATIC_DIR = ROOT_DIR / "static"


class DashboardHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address) -> None:
        _, error, _ = sys.exc_info()
        if isinstance(error, ConnectionError):
            return
        super().handle_error(request, client_address)


class DashboardHandler(DashboardRequestHandler):
    index_file = INDEX_FILE
    static_dir = STATIC_DIR

    def do_GET(self) -> None:
        self.serve_request()

    def do_HEAD(self) -> None:
        self.serve_request()

    def serve_request(self) -> None:
        try:
            parsed = urlparse(self.path)
        except ValueError:
            self.send_error(400, "Invalid request target")
            return
        if self.send_dashboard_asset(parsed.path):
            return
        if parsed.path == "/api/oi":
            self.send_oi_state()
            return
        if parsed.path == "/api/signal-scan":
            self.send_signal_scan_state()
            return
        self.send_error(404)

    def send_oi_state(self):
        poller = getattr(self.server, "poller", None)
        if poller is None:
            self.send_json({"error": "OI poller unavailable"}, status=503)
            return

        poller_thread = getattr(self.server, "poller_thread", None)
        if poller_thread is not None and not poller_thread.is_alive():
            self.send_json({"error": "OI poller stopped"}, status=503)
            return

        try:
            self.send_json(poller.get_state())
        except Exception as exc:
            print(f"{timestamp()} failed to serve OI state: {exc}")
            self.send_json({"error": "OI state unavailable"}, status=503)

    def send_signal_scan_state(self):
        poller = getattr(self.server, "signal_scan_poller", None)
        if poller is None:
            self.send_json({"error": "Signal scan poller unavailable"}, status=503)
            return

        poller_thread = getattr(self.server, "signal_scan_thread", None)
        if poller_thread is not None and not poller_thread.is_alive():
            self.send_json({"error": "Signal scan poller stopped"}, status=503)
            return

        try:
            self.send_json(poller.get_state())
        except Exception as exc:
            print(f"{timestamp()} failed to serve signal scan state: {exc}")
            self.send_json({"error": "Signal scan state unavailable"}, status=503)


def main(argv=None):
    args = parse_args(argv)
    poller = create_poller(args)
    try:
        signal_scan_poller = create_signal_scan_poller(args)
    except Exception as exc:
        print(
            f"{timestamp()} signal scan unavailable; "
            f"continuing with the OI dashboard: {exc}"
        )
        signal_scan_poller = None
    return run_dashboard(args, poller, signal_scan_poller)


def create_poller(args):
    return OIPoller(
        batch_size=args.oi_batch_size,
        batch_delay=args.oi_batch_delay,
        oi_workers=args.oi_workers,
        oi_history_cache_seconds=args.oi_history_cache_seconds,
        ticker_cache_seconds=args.ticker_cache_seconds,
        funding_cache_seconds=args.funding_cache_seconds,
        market_cap_cache_seconds=args.market_cap_cache_seconds,
        snapshot_save_interval=args.snapshot_save_interval,
    )


def create_signal_scan_poller(args):
    return SignalScanPoller(interval_seconds=args.signal_scan_interval)


def run_dashboard(args, poller, signal_scan_poller):
    try:
        server = DashboardHTTPServer((args.host, args.port), DashboardHandler)
    except OSError as exc:
        print(f"无法启动面板: {exc}")
        _close_poller_after_start_failure(poller)
        _close_signal_scan_poller_after_start_failure(signal_scan_poller)
        return 1

    with server:
        server.poller = poller
        server.signal_scan_poller = signal_scan_poller
        thread = create_poller_thread(poller)
        server.poller_thread = thread
        server.signal_scan_thread = None
        try:
            thread.start()
        except Exception as exc:
            print(f"无法启动 OI 轮询线程: {exc}")
            _close_poller_after_start_failure(poller)
            _close_signal_scan_poller_after_start_failure(signal_scan_poller)
            return 1

        signal_scan_thread = _start_optional_signal_scan(
            server,
            signal_scan_poller,
        )

        try:
            log_startup(args)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\nDashboard stopped.")
        finally:
            _stop_poller(poller, thread)
            if signal_scan_thread is not None:
                _stop_signal_scan_poller(signal_scan_poller, signal_scan_thread)
    return 0


def create_poller_thread(poller):
    return threading.Thread(
        target=poller.run_forever,
        name="oi-poller",
        daemon=True,
    )


def create_signal_scan_thread(signal_scan_poller):
    return threading.Thread(
        target=signal_scan_poller.run_forever,
        name="signal-scan-poller",
        daemon=True,
    )


def _start_optional_signal_scan(server, signal_scan_poller):
    if signal_scan_poller is None:
        return None

    try:
        thread = create_signal_scan_thread(signal_scan_poller)
        thread.start()
    except Exception as exc:
        print(
            f"{timestamp()} signal scan unavailable; "
            f"continuing with the OI dashboard: {exc}"
        )
        _close_signal_scan_poller_after_start_failure(signal_scan_poller)
        server.signal_scan_poller = None
        server.signal_scan_thread = None
        return None

    server.signal_scan_thread = thread
    return thread


def log_startup(args):
    print(f"Dashboard running at http://{args.host}:{args.port}")
    print("Price uses Binance futures WebSocket in the browser.")
    print(
        f"OI updates {args.oi_batch_size} symbols every "
        f"{args.oi_batch_delay} seconds with {args.oi_workers} workers."
    )


def _close_poller_after_start_failure(poller):
    try:
        poller.close()
    except Exception as exc:
        print(f"{timestamp()} failed to close OI poller: {exc}")


def _stop_poller(poller, thread):
    poller.stop()
    thread.join(timeout=15)
    if thread.is_alive():
        print(f"{timestamp()} OI poller did not stop within 15 seconds")
        return
    try:
        poller.save_state(force=True)
    except Exception as exc:
        print(f"{timestamp()} failed to save final OI cache: {exc}")


def _close_signal_scan_poller_after_start_failure(signal_scan_poller):
    if signal_scan_poller is None:
        return
    try:
        signal_scan_poller.close()
    except Exception as exc:
        print(f"{timestamp()} failed to close signal scan poller: {exc}")


def _stop_signal_scan_poller(signal_scan_poller, thread):
    signal_scan_poller.stop()
    thread.join(timeout=15)
    if thread.is_alive():
        print(f"{timestamp()} signal scan poller did not stop within 15 seconds")


if __name__ == "__main__":
    raise SystemExit(main())
