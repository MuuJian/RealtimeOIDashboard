"""Lifecycle adapter for pollers that run in background threads."""

from __future__ import annotations

import threading


class BackgroundServiceStopped(RuntimeError):
    """Raised when an HTTP state provider's worker is no longer running."""


class BackgroundPollerService:
    """Run a poller in a thread and expose it as a checked state provider."""

    def __init__(
        self,
        poller,
        *,
        thread_name: str,
        stopped_message: str,
        thread_factory=None,
    ) -> None:
        self.worker = poller
        self.stopped_message = stopped_message
        factory = threading.Thread if thread_factory is None else thread_factory
        self.thread = factory(
            target=poller.run_forever,
            name=thread_name,
            daemon=True,
        )
        self.started = False

    def start(self) -> None:
        self.thread.start()
        self.started = True

    def get_state(self):
        if not self.started or not self.thread.is_alive():
            raise BackgroundServiceStopped(self.stopped_message)
        return self.worker.get_state()

    def stop(self, *, timeout: float) -> bool:
        if not self.started:
            return True
        self.worker.stop()
        self.thread.join(timeout=timeout)
        return not self.thread.is_alive()

    def close(self) -> None:
        self.worker.close()
