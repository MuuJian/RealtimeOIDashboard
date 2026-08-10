"""Bound and retry Signal Scan resource cleanup without blocking shutdown."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class SignalScanCloseSettings:
    attempts: int
    scan_wait_seconds: float
    client_wait_seconds: float
    retry_initial_delay_seconds: float
    retry_max_delay_seconds: float
    retry_max_attempts: int
    log_cooldown_seconds: float


class SignalScanShutdown:
    """Coordinate single-flight client close and bounded deferred retries."""

    def __init__(
        self,
        *,
        lock,
        scan_execution_lock,
        http_client,
        owns_http_client: Callable[[], bool],
        stop_sources: Callable[[], None],
        settings: Callable[[], SignalScanCloseSettings],
        error_text: Callable[[object], str],
        timestamp: Callable[[], str],
    ) -> None:
        self._lock = lock
        self._scan_execution_lock = scan_execution_lock
        self._http_client = http_client
        self._owns_http_client = owns_http_client
        self._stop_sources = stop_sources
        self._settings = settings
        self._error_text = error_text
        self._timestamp = timestamp
        self._close_lock = threading.Lock()
        self._client_close_state_lock = threading.Lock()
        self._client_close_thread = None
        self._client_close_done = None
        self._client_close_result = None
        self.close_retry_wakeup = threading.Event()
        self.close_retry_thread = None
        self.closing = False
        self.closed = False
        self.close_pending = False
        self.close_retry_exhausted = False
        self.close_last_error = None
        self._close_last_logged_at = None

    def close(self) -> None:
        deferred_cleanup_needed = False
        close_error = None
        with self._close_lock:
            with self._lock:
                if self.closed:
                    return
                self.closing = True
                self._stop_sources()

            if self._owns_http_client():
                acquired = self._scan_execution_lock.acquire(
                    timeout=self._settings().scan_wait_seconds
                )
                if not acquired:
                    with self._lock:
                        self.close_pending = True
                        self.close_retry_exhausted = False
                        self.close_last_error = "signal scan is still running"
                    deferred_cleanup_needed = True
                else:
                    try:
                        self.close_owned_http_client()
                    except Exception as exc:
                        with self._lock:
                            self.close_pending = True
                            self.close_retry_exhausted = False
                            self.close_last_error = self._error_text(exc)
                        close_error = exc
                        deferred_cleanup_needed = True
                    finally:
                        self._scan_execution_lock.release()

            if not deferred_cleanup_needed and close_error is None:
                with self._lock:
                    self.closed = True
                    self.close_pending = False
                    self.close_retry_exhausted = False
                    self.close_last_error = None
                self.close_retry_wakeup.set()

        if deferred_cleanup_needed:
            self.schedule_deferred_close()
            if close_error is None:
                raise TimeoutError("signal scan is still running")
        if close_error is not None:
            raise close_error

    def close_owned_http_client(self) -> None:
        """Run an owned client's close once and bound the caller's wait."""
        with self._client_close_state_lock:
            done = self._client_close_done
            result = self._client_close_result
            if (
                done is None
                or (
                    done.is_set()
                    and result.get("error") is not None
                    and (
                        self._client_close_thread is None
                        or not self._client_close_thread.is_alive()
                    )
                )
            ):
                done = threading.Event()
                result = {}
                self._client_close_done = done
                self._client_close_result = result
                self._client_close_thread = threading.Thread(
                    target=_run_client_close,
                    args=(self._http_client, done, result, self._error_text),
                    name="signal-scan-http-cleanup",
                    daemon=True,
                )
                self._client_close_thread.start()

        if not done.wait(self._settings().client_wait_seconds):
            raise TimeoutError("signal scan HTTP client close is still running")
        error = result.get("error")
        if error is not None:
            raise error

    def close_after_polling(self) -> None:
        last_error = None
        for _ in range(self._settings().attempts):
            try:
                self.close()
                return
            except Exception as exc:
                last_error = exc
        self.log_close_failure(last_error)
        self.schedule_deferred_close()

    def schedule_deferred_close(self) -> None:
        with self._close_lock:
            with self._lock:
                if (
                    self.closed
                    or not self.close_pending
                    or self.close_retry_exhausted
                ):
                    return
            if (
                self.close_retry_thread is not None
                and self.close_retry_thread.is_alive()
            ):
                return
            self.close_retry_thread = threading.Thread(
                target=self.retry_close_until_success,
                name="signal-scan-cleanup",
                daemon=True,
            )
            self.close_retry_thread.start()

    def retry_close_until_success(self) -> None:
        settings = self._settings()
        delay = settings.retry_initial_delay_seconds
        last_error = None
        for _ in range(settings.retry_max_attempts):
            if self.close_retry_wakeup.wait(delay):
                return
            try:
                self.close()
                return
            except Exception as exc:
                last_error = exc
                self.log_close_failure(exc, deferred=True)
                delay = min(
                    delay * 2,
                    self._settings().retry_max_delay_seconds,
                )
        with self._lock:
            self.close_pending = True
            self.close_last_error = self._error_text(last_error)
            self.close_retry_exhausted = True
        self.log_close_failure(last_error, deferred=True, force=True)

    def log_close_failure(
        self,
        error,
        *,
        deferred: bool = False,
        force: bool = False,
    ) -> None:
        now = time.monotonic()
        with self._lock:
            previous = self._close_last_logged_at
            if (
                not force
                and previous is not None
                and now >= previous
                and now - previous < self._settings().log_cooldown_seconds
            ):
                return
            self._close_last_logged_at = now
            message = self.close_last_error or self._error_text(error)
        prefix = "deferred " if deferred else ""
        print(
            f"{self._timestamp()} {prefix}signal scan cleanup failed: {message}"
        )


def _run_client_close(client, done, result, error_text) -> None:
    try:
        client.close()
    except BaseException as error:
        result["error"] = (
            error
            if isinstance(error, Exception)
            else RuntimeError(error_text(error))
        )
    finally:
        done.set()
