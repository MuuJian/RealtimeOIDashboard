"""HTTP response helpers for the realtime OI dashboard."""

from __future__ import annotations

import gzip
import hashlib
import json
import mimetypes
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any


API_CACHE_CONTROL = "private, no-cache, must-revalidate"
INDEX_CACHE_CONTROL = "no-cache"
STATIC_CACHE_CONTROL = "public, no-cache, must-revalidate"


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """Serve one dashboard page, static assets, and JSON responses safely."""

    protocol_version = "HTTP/1.1"
    timeout = 30
    index_file: Path
    static_dir: Path

    def send_response(self, code: int, message: str | None = None) -> None:
        super().send_response(code, message)
        self.send_header(
            "Cache-Control",
            getattr(self, "_response_cache_control", "no-store"),
        )
        self.send_header("X-Content-Type-Options", "nosniff")

    def send_dashboard_asset(self, request_path: str) -> bool:
        """Serve the index or a static file and report whether it matched."""
        if request_path in {"/", "/index.html"}:
            self.send_file(
                self.index_file,
                "text/html; charset=utf-8",
                cache_control=INDEX_CACHE_CONTROL,
            )
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
        self.send_file(
            file_path,
            content_type,
            cache_control=STATIC_CACHE_CONTROL,
        )

    def send_file(
        self,
        path: Path,
        content_type: str,
        *,
        cache_control: str = "no-store",
    ) -> None:
        try:
            body = path.read_bytes()
        except OSError:
            self.send_error(404)
            return

        self._send_body(
            body,
            content_type=content_type,
            cache_control=cache_control,
            etag=_content_etag(body),
        )

    def send_json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        content_encoding = None
        response_body = body
        if _accepts_gzip(self.headers.get("Accept-Encoding")):
            response_body = gzip.compress(body, compresslevel=6, mtime=0)
            content_encoding = "gzip"

        cacheable = status == 200
        self._send_body(
            response_body,
            content_type="application/json; charset=utf-8",
            status=status,
            cache_control=API_CACHE_CONTROL if cacheable else "no-store",
            content_encoding=content_encoding,
            etag=_content_etag(body, weak=True) if cacheable else None,
            vary=("Accept-Encoding",),
        )

    def _send_body(
        self,
        body: bytes,
        *,
        content_type: str,
        status: int = 200,
        cache_control: str = "no-store",
        content_encoding: str | None = None,
        etag: str | None = None,
        vary: tuple[str, ...] = (),
    ) -> None:
        try:
            if status == 200 and etag and self._if_none_match_matches(etag):
                self._send_not_modified(
                    cache_control=cache_control,
                    content_encoding=content_encoding,
                    etag=etag,
                    vary=vary,
                )
                return

            self._start_response(status, cache_control)
            self.send_header("Content-Type", content_type)
            if content_encoding:
                self.send_header("Content-Encoding", content_encoding)
            if etag:
                self.send_header("ETag", etag)
            self._send_vary(vary)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)
        except OSError:
            self.close_connection = True

    def _send_not_modified(
        self,
        *,
        cache_control: str,
        content_encoding: str | None,
        etag: str,
        vary: tuple[str, ...],
    ) -> None:
        self._start_response(304, cache_control)
        if content_encoding:
            self.send_header("Content-Encoding", content_encoding)
        self.send_header("ETag", etag)
        self._send_vary(vary)
        self.end_headers()

    def _start_response(self, status: int, cache_control: str) -> None:
        self._response_cache_control = cache_control
        try:
            self.send_response(status)
        finally:
            del self._response_cache_control

    def _send_vary(self, fields: tuple[str, ...]) -> None:
        if fields:
            self.send_header("Vary", ", ".join(fields))

    def _if_none_match_matches(self, etag: str) -> bool:
        if self.command not in {"GET", "HEAD"}:
            return False
        value = self.headers.get("If-None-Match")
        if not value:
            return False
        expected = _strip_weak_prefix(etag)
        return any(
            candidate.strip() == "*" or _strip_weak_prefix(candidate) == expected
            for candidate in value.split(",")
            if candidate.strip()
        )

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


def _accepts_gzip(value: str | None) -> bool:
    if not value:
        return False

    gzip_quality = None
    wildcard_quality = None
    for item in value.split(","):
        parts = [part.strip() for part in item.split(";")]
        coding = parts[0].lower()
        quality = 1.0
        for parameter in parts[1:]:
            name, separator, raw_value = parameter.partition("=")
            if separator and name.strip().lower() == "q":
                try:
                    quality = float(raw_value.strip())
                except ValueError:
                    quality = 0.0
                quality = min(1.0, max(0.0, quality))
                break
        if coding == "gzip":
            gzip_quality = quality
        elif coding == "*":
            wildcard_quality = quality

    selected_quality = gzip_quality
    if selected_quality is None:
        selected_quality = wildcard_quality
    return selected_quality is not None and selected_quality > 0


def _content_etag(body: bytes, *, weak: bool = False) -> str:
    digest = hashlib.sha256(body).hexdigest()
    prefix = "W/" if weak else ""
    return f'{prefix}"{digest}"'


def _strip_weak_prefix(value: str) -> str:
    stripped = value.strip()
    return stripped[2:].lstrip() if stripped[:2].lower() == "w/" else stripped
