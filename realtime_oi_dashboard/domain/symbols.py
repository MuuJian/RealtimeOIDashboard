"""Binance symbol validation for the realtime OI dashboard."""

from __future__ import annotations


def is_valid_binance_symbol(value: object) -> bool:
    """Return whether *value* is a non-empty uppercase ASCII symbol."""
    return (
        isinstance(value, str)
        and value.isascii()
        and value.isalnum()
        and value == value.upper()
    )
