"""Pure time-series rules for signal-scan Binance klines."""

from __future__ import annotations


KLINE_INTERVAL_MILLISECONDS = 60 * 60 * 1000
KLINE_MAX_RESPONSE_ROWS = 1500
KLINE_MIN_FIELDS = 5


def copy_kline_history(klines: list) -> list:
    """Return a mutable copy without sharing candle rows with the caller."""
    return [list(candle) for candle in klines]


def merge_kline_history(
    cached: object,
    updates: object,
    *,
    limit: int,
) -> list | None:
    """Merge a small contiguous refresh into a cached history window."""
    if (
        not _is_positive_limit(limit)
        or not isinstance(cached, list)
        or not isinstance(updates, list)
        or not cached
        or not updates
        or len(cached) > limit
        or len(updates) > KLINE_MAX_RESPONSE_ROWS
        or not _is_kline_rows(cached)
        or not _is_kline_rows(updates)
    ):
        return None

    cached_copy = copy_kline_history(cached)
    updates_copy = copy_kline_history(updates)
    if not _has_contiguous_open_times(cached_copy) or not _has_contiguous_open_times(
        updates_copy
    ):
        return None

    cached_keys = [_kline_open_time(candle) for candle in cached_copy]
    update_keys = [_kline_open_time(candle) for candle in updates_copy]
    if update_keys[-1] < cached_keys[-1]:
        return None

    if len(updates_copy) >= limit:
        return updates_copy[-limit:]

    if (
        update_keys[0] > cached_keys[-1]
        and update_keys[0] - cached_keys[-1] != KLINE_INTERVAL_MILLISECONDS
    ):
        return None

    updates_by_key = dict(zip(update_keys, updates_copy))
    merged = [
        candle
        for candle, key in zip(cached_copy, cached_keys)
        if key not in updates_by_key
    ]
    merged.extend(updates_copy)
    merged.sort(key=_kline_open_time)
    if not _has_contiguous_open_times(merged):
        return None
    return merged[-limit:]


def normalize_kline_history(value: object, *, limit: int) -> list | None:
    """Validate and copy a bounded contiguous kline response."""
    if (
        not _is_positive_limit(limit)
        or not isinstance(value, list)
        or len(value) > KLINE_MAX_RESPONSE_ROWS
        or not _is_kline_rows(value)
        or not _has_contiguous_open_times(value)
    ):
        return None
    return copy_kline_history(value[-limit:])


def _is_positive_limit(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_kline_rows(value: list) -> bool:
    return all(
        isinstance(candle, (list, tuple)) and len(candle) >= KLINE_MIN_FIELDS
        for candle in value
    )


def _has_contiguous_open_times(rows: list) -> bool:
    if not rows:
        return False

    previous = None
    for candle in rows:
        current = _kline_open_time(candle)
        if (
            current is None
            or current % KLINE_INTERVAL_MILLISECONDS != 0
            or (
                previous is not None
                and current - previous != KLINE_INTERVAL_MILLISECONDS
            )
        ):
            return False
        previous = current
    return True


def _kline_open_time(candle: list | tuple) -> int | None:
    raw_value = candle[0]
    if isinstance(raw_value, bool):
        return None
    try:
        parsed = int(raw_value)
        if float(raw_value) != parsed:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if parsed >= 0 else None
