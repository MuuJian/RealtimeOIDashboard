"""Schedule CVD snapshot restoration and persistence."""

from __future__ import annotations

from realtime_oi_dashboard.domain.cvd.model import MINUTE_MS


class CvdSnapshotService:
    def __init__(
        self,
        repository,
        store,
        *,
        enabled: bool,
        persist_minutes: int,
        interval_seconds: float,
        now_ms,
        monotonic,
        is_stopped,
    ) -> None:
        self._repository = repository
        self._store = store
        self._enabled = bool(enabled)
        self._persist_minutes = int(persist_minutes)
        self._interval_seconds = float(interval_seconds)
        self._now_ms = now_ms
        self._monotonic = monotonic
        self._is_stopped = is_stopped
        self._last_persist_at = None
        self.error = None

    def restore(self) -> None:
        if not self._enabled:
            return
        try:
            records, saved_at = self._repository.load(now_ms=self._now_ms())
            if saved_at is not None:
                self._store.restore(records, updated_at=saved_at)
            self.error = None
        except (OSError, ValueError, RecursionError) as exc:
            self.error = str(exc)

    def save_if_due(self) -> None:
        if not self._enabled:
            return
        now = self._monotonic()
        if (
            self._last_persist_at is not None
            and now - self._last_persist_at < self._interval_seconds
        ):
            return
        self.save()

    def save(self, *, force=False) -> None:
        if not self._enabled or (self._is_stopped() and not force):
            return
        saved_at = self._now_ms()
        cutoff = saved_at - self._persist_minutes * MINUTE_MS
        try:
            self._repository.save(
                saved_at=saved_at,
                symbols=self._store.export(cutoff_ms=cutoff),
            )
            self._last_persist_at = self._monotonic()
            self.error = None
        except (OSError, ValueError) as exc:
            self.error = str(exc)
