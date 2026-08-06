"""Persistent symbol and OI-history cache loading and serialization."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from realtime_oi_dashboard.infrastructure.file_io import write_text_atomic
from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol


MAX_SNAPSHOT_FILE_BYTES = 5 * 1024 * 1024


@dataclass(slots=True)
class LoadedSnapshot:
    known_symbols: set[str] = field(default_factory=set)
    oi_history: dict[str, dict[str, Any]] = field(default_factory=dict)


class SnapshotRepository:
    """Read and atomically replace one on-disk OI snapshot."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> LoadedSnapshot:
        return load_snapshot_file(self.path)

    def save(self, *, symbols, saved_at, oi_history) -> None:
        write_snapshot_file(
            self.path,
            symbols=symbols,
            saved_at=saved_at,
            oi_history=oi_history,
        )


class SnapshotService:
    """Apply save throttling around the snapshot repository."""

    def __init__(
        self,
        repository: SnapshotRepository,
        symbols_provider,
        oi_history_provider,
        *,
        save_interval: float,
        iso_now,
        timestamp,
        log=print,
        monotonic=time.monotonic,
    ) -> None:
        self.repository = repository
        self.symbols_provider = symbols_provider
        self.oi_history_provider = oi_history_provider
        self.save_interval = save_interval
        self.iso_now = iso_now
        self.timestamp = timestamp
        self.log = log
        self.monotonic = monotonic
        self.save_lock = threading.Lock()
        self.last_save = None

    def load(self) -> LoadedSnapshot:
        try:
            return self.repository.load()
        except (OSError, ValueError, RecursionError) as exc:
            self.log(
                f"{self.timestamp()} failed to load previous OI cache: {exc}"
            )
            return LoadedSnapshot()

    def save(self, *, force=False) -> bool:
        with self.save_lock:
            now = self.monotonic()
            if (
                not force
                and self.save_interval > 0
                and self.last_save is not None
                and now - self.last_save < self.save_interval
            ):
                return False

            self.repository.save(
                symbols=self.symbols_provider(),
                saved_at=self.iso_now(),
                oi_history=self.oi_history_provider(),
            )
            self.last_save = self.monotonic()
            return True

    def reset_schedule(self) -> None:
        with self.save_lock:
            self.last_save = None


def load_snapshot_file(path: Path) -> LoadedSnapshot:
    """Load the last known symbol set and validated history-cache container."""
    if not path.exists():
        return LoadedSnapshot()

    payload = json.loads(_read_snapshot_text(path))
    if not isinstance(payload, dict):
        return LoadedSnapshot()

    known_symbols = _valid_symbols(payload.get("symbols"))
    legacy_snapshot = payload.get("snapshot")
    if isinstance(legacy_snapshot, dict):
        known_symbols.update(
            symbol
            for symbol in legacy_snapshot
            if is_valid_binance_symbol(symbol)
        )
    raw_oi_history = payload.get("oi_history")
    oi_history = (
        dict(raw_oi_history)
        if isinstance(raw_oi_history, dict)
        else {}
    )

    return LoadedSnapshot(
        known_symbols=known_symbols,
        oi_history=oi_history,
    )


def write_snapshot_file(
    path: Path,
    *,
    symbols: set[str] | list[str],
    saved_at: str,
    oi_history: dict[str, dict[str, Any]] | None = None,
) -> None:
    """Atomically serialize restart-safe symbol and history-cache state."""
    payload = {
        "saved_at": saved_at,
        "symbols": sorted(symbols),
        "oi_history": oi_history or {},
    }
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(text.encode("utf-8")) > MAX_SNAPSHOT_FILE_BYTES:
        raise ValueError(
            f"OI cache exceeds {MAX_SNAPSHOT_FILE_BYTES} bytes"
        )
    write_text_atomic(path, text)


def _valid_symbols(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {symbol for symbol in value if is_valid_binance_symbol(symbol)}


def _read_snapshot_text(path: Path) -> str:
    with path.open("rb") as file:
        raw_payload = file.read(MAX_SNAPSHOT_FILE_BYTES + 1)
    if len(raw_payload) > MAX_SNAPSHOT_FILE_BYTES:
        raise ValueError(
            f"OI cache exceeds {MAX_SNAPSHOT_FILE_BYTES} bytes"
        )
    return raw_payload.decode("utf-8")
