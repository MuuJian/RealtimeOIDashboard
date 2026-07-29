"""Persistent symbol and OI-history cache loading and serialization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from realtime_oi_dashboard.file_io import write_text_atomic
from realtime_oi_dashboard.symbols import is_valid_binance_symbol


MAX_SNAPSHOT_FILE_BYTES = 5 * 1024 * 1024


@dataclass(slots=True)
class LoadedSnapshot:
    known_symbols: set[str] = field(default_factory=set)
    oi_history: dict[str, dict[str, Any]] = field(default_factory=dict)


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
