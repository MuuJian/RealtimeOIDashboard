"""Thread-safe JSON HTTP client for Binance API requests."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import timezone
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import Any

import requests


RETRYABLE_STATUS_CODES = frozenset({408, 418, 429, 500, 502, 503, 504})
NON_RETRYABLE_REQUEST_ERRORS = (
    requests.exceptions.InvalidHeader,
    requests.exceptions.InvalidSchema,
    requests.exceptions.InvalidURL,
    requests.exceptions.MissingSchema,
    requests.exceptions.TooManyRedirects,
    requests.exceptions.URLRequired,
)


class JsonHttpClient:
    """Thread-safe JSON client with one requests session per worker thread."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], requests.Session] = requests.Session,
        sleep: Callable[[float], None] = time.sleep,
        check_cancelled: Callable[[], None] | None = None,
        retry_base_delay: float = 1.0,
    ) -> None:
        if isinstance(retry_base_delay, bool):
            raise ValueError("retry_base_delay must be a finite non-negative number")
        try:
            retry_base_delay = float(retry_base_delay)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(
                "retry_base_delay must be a finite non-negative number"
            ) from exc
        if not isfinite(retry_base_delay) or retry_base_delay < 0:
            raise ValueError("retry_base_delay must be a finite non-negative number")
        self._session_factory = session_factory
        self._sleep = sleep
        self._check_cancelled = check_cancelled
        self._retry_base_delay = retry_base_delay
        self._thread_local = threading.local()
        self._sessions_lock = threading.Lock()
        self._sessions: list[requests.Session] = []
        self._closed = False

    def get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 10,
        attempts: int = 3,
    ) -> Any:
        """GET *url* and decode JSON, retrying transient request failures."""
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts <= 0:
            raise ValueError("attempts must be greater than 0")
        if isinstance(timeout, bool):
            raise ValueError("timeout must be a finite positive number")
        try:
            timeout = float(timeout)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("timeout must be a finite positive number") from exc
        if not isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite positive number")

        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            self._raise_if_cancelled()
            try:
                response = self._session().get(url, params=params, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException as exc:
                error = exc
            else:
                self._raise_if_cancelled()
                try:
                    payload = response.json()
                except RecursionError:
                    error = ValueError("response JSON nesting is too deep")
                except ValueError as exc:
                    error = exc
                else:
                    self._raise_if_cancelled()
                    return payload

            self._raise_if_cancelled()
            last_error = error
            if attempt == attempts or not self._should_retry(error):
                break
            self._sleep(self._retry_delay(attempt, error))

        assert last_error is not None
        raise last_error

    def _raise_if_cancelled(self) -> None:
        if self._check_cancelled is not None:
            self._check_cancelled()

    def _session(self) -> requests.Session:
        with self._sessions_lock:
            if self._closed:
                raise RuntimeError("HTTP client is closed")
        session = getattr(self._thread_local, "session", None)
        if session is None:
            session = self._session_factory()
            with self._sessions_lock:
                client_closed = self._closed
                if not client_closed:
                    self._sessions.append(session)
            if client_closed:
                try:
                    session.close()
                except BaseException:
                    # The client state is the reason this session is unusable.
                    pass
                raise RuntimeError("HTTP client is closed")
            self._thread_local.session = session
        return session

    def close(self) -> None:
        """Close every worker session after callers have stopped using the client."""
        with self._sessions_lock:
            if self._closed and not self._sessions:
                return
            self._closed = True
            sessions = self._sessions
            self._sessions = []

        errors = []
        failed_sessions = []
        for session in {id(item): item for item in sessions}.values():
            try:
                session.close()
            except BaseException as error:
                errors.append(error)
                failed_sessions.append(session)

        if failed_sessions:
            with self._sessions_lock:
                self._sessions.extend(failed_sessions)
            raise errors[0]

    def _should_retry(self, exc: Exception) -> bool:
        if isinstance(exc, NON_RETRYABLE_REQUEST_ERRORS):
            return False
        response = getattr(exc, "response", None)
        return response is None or response.status_code in RETRYABLE_STATUS_CODES

    def _retry_delay(self, attempt: int, exc: Exception) -> float:
        response = getattr(exc, "response", None)
        base_delay = self._retry_base_delay * attempt
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                delay = _retry_after_seconds(retry_after)
                if delay is not None:
                    minimum = 2.0 * attempt if response.status_code in {418, 429} else base_delay
                    return max(delay, minimum)
            if response.status_code in {418, 429}:
                return 10.0 * attempt
        return base_delay


def _retry_after_seconds(value: str) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at is None:
                return None
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = retry_at.timestamp() - time.time()
        except (OSError, TypeError, ValueError, OverflowError):
            return None
        return max(seconds, 0.0) if isfinite(seconds) else None

    if not isfinite(seconds) or seconds < 0:
        return None
    return seconds
