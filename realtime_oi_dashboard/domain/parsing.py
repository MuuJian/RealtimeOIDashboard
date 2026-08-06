"""Strict numeric conversion helpers for Binance API payloads."""

from __future__ import annotations

from math import isfinite


def optional_float(value: object, *, multiplier: float = 1) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value) * multiplier
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) else None


def optional_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, str):
        candidate = value.strip()
        digits = candidate[1:] if candidate[:1] in {"+", "-"} else candidate
        if not digits or not digits.isdecimal():
            return None
        try:
            return int(candidate)
        except (ValueError, OverflowError):
            return None

    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    try:
        return parsed if value == parsed else None
    except Exception:
        return None
