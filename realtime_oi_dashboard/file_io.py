"""Safe local file writes for the dashboard snapshot cache."""

from __future__ import annotations

from pathlib import Path
from stat import S_ISREG
from uuid import uuid4


def write_text_atomic(path: Path, text: str) -> None:
    """Write UTF-8 text without exposing a partially written destination."""
    _regular_file_exists(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        _regular_file_exists(path)
        temp_path.replace(path)
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


def _regular_file_exists(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return False
    if not S_ISREG(mode):
        raise OSError(f"expected a regular file: {path}")
    return True
