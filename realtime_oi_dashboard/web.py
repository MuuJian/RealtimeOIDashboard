"""HTTP response helpers for the realtime OI dashboard."""

from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """Serve one dashboard page, static assets, and JSON responses safely."""

    protocol_version = "HTTP/1.1"
    timeout = 30
    index_file: Path
    static_dir: Path

    def send_response(self, code: int, message: str | None = None) -> None:
        super().send_response(code, message)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

    def send_dashboard_asset(self, request_path: str) -> bool:
        """Serve the index or a static file and report whether it matched."""
        if request_path in {"/", "/index.html"}:
            self.send_file(self.index_file, "text/html; charset=utf-8")
            return True
        if request_path.startswith("/static/"):
            self.send_static(request_path)
            return True
        return False

    def send_static(self, request_path: str) -> None:
        relative_path = request_path.removeprefix("/static/")
        try:
            file_path = (self.static_dir / relative_path).resolve()
            static_root = self.static_dir.resolve()
        except (OSError, RuntimeError, ValueError):
            self.send_error(404)
            return

        if not file_path.is_relative_to(static_root):
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        if file_path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif file_path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        self.send_file(file_path, content_type)

    def send_file(self, path: Path, content_type: str) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404)
            return

        self._send_body(body, content_type=content_type)

    def send_json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self._send_body(
            body,
            content_type="application/json; charset=utf-8",
            status=status,
        )

    def _send_body(self, body: bytes, *, content_type: str, status: int = 200) -> None:
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except OSError:
            self.close_connection = True

    def send_error(
        self,
        code: int,
        message: str | None = None,
        explain: str | None = None,
    ) -> None:
        try:
            super().send_error(code, message, explain)
        except OSError:
            self.close_connection = True

    def log_message(self, format: str, *args: object) -> None:
        return
