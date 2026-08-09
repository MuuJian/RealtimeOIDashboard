"""HTTP transport for the realtime OI dashboard."""

from __future__ import annotations

import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from realtime_oi_dashboard.application.background_service import (
    BackgroundServiceStopped,
)
from realtime_oi_dashboard.application.oi.poller import timestamp
from realtime_oi_dashboard.web import DashboardRequestHandler


ROOT_DIR = Path(__file__).resolve().parent
INDEX_FILE = ROOT_DIR / "index.html"
STATIC_DIR = ROOT_DIR / "static"


class DashboardHTTPServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address,
        request_handler_class,
        *,
        oi_state_provider,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.oi_state_provider = oi_state_provider

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
        self.send_error(404)

    def send_oi_state(self):
        provider = getattr(self.server, "oi_state_provider", None)
        if provider is None:
            self.send_json({"error": "OI poller unavailable"}, status=503)
            return
        try:
            self.send_json(provider.get_state())
        except BackgroundServiceStopped as exc:
            self.send_json({"error": str(exc)}, status=503)
        except Exception as exc:
            print(f"{timestamp()} failed to serve OI state: {exc}")
            self.send_json({"error": "OI state unavailable"}, status=503)

def create_dashboard_server(
    host,
    port,
    *,
    oi_state_provider,
):
    return DashboardHTTPServer(
        (host, port),
        DashboardHandler,
        oi_state_provider=oi_state_provider,
    )
