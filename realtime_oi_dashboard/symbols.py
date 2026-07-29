"""Binance symbol validation for the realtime OI dashboard."""

from __future__ import annotations


def is_valid_binance_symbol(value: object) -> bool:
    """Return whether *value* contains only Binance symbol characters."""
    return isinstance(value, str) and value.isalnum()
