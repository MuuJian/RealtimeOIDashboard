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
        signal_scan_state_provider=None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.oi_state_provider = oi_state_provider
        self.signal_scan_state_provider = signal_scan_state_provider

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
        if parsed.path == "/livez":
            self.send_json({"status": "ok"})
            return
        if parsed.path == "/readyz":
            self.send_readiness()
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

    def send_signal_scan_state(self):
        provider = getattr(self.server, "signal_scan_state_provider", None)
        if provider is None:
            self.send_json({"error": "Signal scan poller unavailable"}, status=503)
            return
        try:
            self.send_json(provider.get_state())
        except BackgroundServiceStopped as exc:
            self.send_json({"error": str(exc)}, status=503)
        except Exception as exc:
            print(f"{timestamp()} failed to serve signal scan state: {exc}")
            self.send_json({"error": "Signal scan state unavailable"}, status=503)

    def send_readiness(self) -> None:
        oi_state, oi_summary = _oi_readiness(
            getattr(self.server, "oi_state_provider", None)
        )
        ready = oi_state is not None
        payload = {
            "status": "ready" if ready else "not_ready",
            "components": {
                "oi": oi_summary,
                "signalScan": _signal_scan_readiness(
                    getattr(self.server, "signal_scan_state_provider", None)
                ),
                "cvd": _cvd_readiness(oi_state),
            },
        }
        self.send_json(payload, status=200 if ready else 503)


def _oi_readiness(provider):
    if provider is None:
        return None, {"status": "unavailable", "rows": 0}
    try:
        state = provider.get_state()
    except BackgroundServiceStopped:
        return None, {"status": "stopped", "rows": 0}
    except Exception:
        return None, {"status": "error", "rows": 0}

    if not isinstance(state, dict):
        return None, {"status": "invalid", "rows": 0}
    rows = state.get("rows")
    if not isinstance(rows, list):
        return None, {"status": "invalid", "rows": 0}
    row_count = sum(
        isinstance(row, dict)
        and isinstance(row.get("symbol"), str)
        and bool(row["symbol"])
        for row in rows
    )
    if row_count == 0:
        return None, {"status": "warming", "rows": 0}
    component_status = "degraded" if state.get("error") else "ready"
    return state, {"status": component_status, "rows": row_count}


def _signal_scan_readiness(provider) -> dict:
    if provider is None:
        return {"status": "unavailable", "signals": 0}
    try:
        state = provider.get_state()
    except BackgroundServiceStopped:
        return {"status": "stopped", "signals": 0}
    except Exception:
        return {"status": "error", "signals": 0}

    if not isinstance(state, dict):
        return {"status": "invalid", "signals": 0}
    groups = [state.get(name) for name in ("bulls", "bears", "spikes")]
    if not all(isinstance(group, list) for group in groups):
        return {"status": "invalid", "signals": 0}
    signal_count = sum(
        isinstance(signal, dict)
        for group in groups
        for signal in group
    )
    if state.get("error") or state.get("partial"):
        status = "degraded"
    elif state.get("saved_at") is None:
        status = "warming"
    else:
        status = "ready"
    return {"status": status, "signals": signal_count}


def _cvd_readiness(oi_state) -> dict:
    if not isinstance(oi_state, dict):
        return {"status": "unavailable", "health": "unavailable"}
    meta = oi_state.get("cvd_meta")
    if not isinstance(meta, dict):
        return {"status": "unavailable", "health": "unavailable"}
    health = meta.get("serviceHealth")
    if health == "live":
        status = "ready"
    elif health == "warming":
        status = "warming"
    elif health in {"partial", "stale"}:
        status = "degraded"
    else:
        health = "unavailable"
        status = "unavailable"
    return {"status": status, "health": health}


def create_dashboard_server(
    host,
    port,
    *,
    oi_state_provider,
    signal_scan_state_provider=None,
):
    return DashboardHTTPServer(
        (host, port),
        DashboardHandler,
        oi_state_provider=oi_state_provider,
        signal_scan_state_provider=signal_scan_state_provider,
    )
