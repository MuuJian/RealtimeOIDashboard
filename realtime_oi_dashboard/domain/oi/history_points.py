"""Parse and calculate open-interest history points."""

from __future__ import annotations

from math import isfinite

from realtime_oi_dashboard.domain.parsing import optional_float, optional_int


MAX_SAFE_INTEGER = 2**53 - 1
HOUR_MS = 60 * 60 * 1000
HISTORY_BASELINE_TOLERANCE_MS = 2 * HOUR_MS


def parse_oi_history_points(response):
    if not isinstance(response, list):
        raise ValueError("unexpected OI history response")

    history_points = []
    for item in response:
        if not isinstance(item, dict):
            continue
        timestamp_ms = optional_int(item.get("timestamp"))
        if (
            timestamp_ms is None
            or timestamp_ms <= 0
            or timestamp_ms > MAX_SAFE_INTEGER
        ):
            continue
        history_points.append((timestamp_ms, item))
    history_points.sort(key=lambda point: point[0])
    return history_points


def history_open_interest_point(history_points, target_timestamp_ms, label):
    """Return the nearest usable OI and implied price at or before a target."""
    saw_invalid_value = False
    for timestamp_ms, item in reversed(history_points):
        if timestamp_ms > target_timestamp_ms:
            continue
        if target_timestamp_ms - timestamp_ms > HISTORY_BASELINE_TOLERANCE_MS:
            break

        open_interest = optional_float(item.get("sumOpenInterest"))
        if open_interest is None or open_interest < 0:
            saw_invalid_value = True
            continue
        return timestamp_ms, open_interest, _history_implied_price(
            item,
            open_interest,
        )

    if saw_invalid_value:
        raise ValueError(f"invalid {label} OI history")
    return None


def history_point_value(point, target_timestamp_ms):
    """Return a cached history value only while its source remains in range."""
    if not history_point_is_usable(point, target_timestamp_ms):
        return None
    return point[1]


def history_point_price(point, target_timestamp_ms):
    """Return the implied historical price while its source remains in range."""
    if not history_point_is_usable(point, target_timestamp_ms):
        return None
    return point[2]


def calculate_change_percent(current_value, previous_value):
    if previous_value is None or previous_value <= 0:
        return None
    change_percent = (current_value - previous_value) / previous_value * 100
    return change_percent if isfinite(change_percent) else None


def history_point_is_usable(point, target_timestamp_ms):
    """Report whether a cached point still covers an exchange-time target."""
    if point is None:
        return False
    timestamp_ms = point[0]
    return (
        timestamp_ms <= target_timestamp_ms
        and target_timestamp_ms - timestamp_ms
        <= HISTORY_BASELINE_TOLERANCE_MS
    )


def _history_implied_price(item, open_interest):
    if open_interest <= 0:
        return None
    open_interest_value = optional_float(item.get("sumOpenInterestValue"))
    if open_interest_value is None or open_interest_value <= 0:
        return None
    price = open_interest_value / open_interest
    return price if isfinite(price) and price > 0 else None
