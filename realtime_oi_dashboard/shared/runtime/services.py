"""Uniform lifecycle operations for independently managed services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LifecycleFailure:
    key: str
    label: str
    error: Exception


@dataclass(frozen=True, slots=True)
class StopResult:
    key: str
    label: str
    stopped: bool
    error: Exception | None = None


class ServiceGroup:
    """Address optional services by name and apply lifecycle operations."""

    def __init__(self, **services) -> None:
        self._services = {
            key: (label, service)
            for key, (label, service) in services.items()
            if service is not None
        }

    def start(self, key: str) -> None:
        _label, service = self._services[key]
        service.start()

    def close(self, key: str) -> LifecycleFailure | None:
        entry = self._services.get(key)
        if entry is None:
            return None
        label, service = entry
        try:
            service.close()
        except Exception as exc:
            return LifecycleFailure(key, label, exc)
        return None

    def close_all(self) -> list[LifecycleFailure]:
        failures = []
        for key in self._services:
            failure = self.close(key)
            if failure is not None:
                failures.append(failure)
        return failures

    def stop(self, key: str, *, timeout: float) -> StopResult | None:
        entry = self._services.get(key)
        if entry is None:
            return None
        label, service = entry
        try:
            stopped = service.stop(timeout=timeout)
        except Exception as exc:
            return StopResult(key, label, False, exc)
        return StopResult(key, label, bool(stopped))
