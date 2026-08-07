"""Pure rolling Cumulative Volume Delta calculations."""

from __future__ import annotations

from collections import deque
from math import isfinite


WINDOW_SECONDS = 15 * 60
STATUS_THRESHOLD = 0.10


class RollingCvdWindow:
    """Keep a bounded per-symbol window of signed taker notional."""

    def __init__(
        self,
        *,
        window_seconds=WINDOW_SECONDS,
        coverage_seconds=WINDOW_SECONDS,
        now_ms=0,
    ):
        self.window_ms = _positive_milliseconds(window_seconds)
        self.coverage_ms = _positive_milliseconds(coverage_seconds)
        self.events_by_symbol = {}
        self.coverage_started_at = {}
        self.tracked_symbols = set()
        self.set_tracked_symbols(set(), now_ms=now_ms)

    def set_tracked_symbols(self, symbols, *, now_ms):
        now_ms = _timestamp_ms(now_ms)
        tracked = {symbol for symbol in symbols if _is_symbol(symbol)}
        removed = self.tracked_symbols - tracked
        for symbol in removed:
            self.events_by_symbol.pop(symbol, None)
            self.coverage_started_at.pop(symbol, None)
        for symbol in tracked - self.tracked_symbols:
            self.events_by_symbol[symbol] = deque()
            self.coverage_started_at[symbol] = now_ms
        self.tracked_symbols = tracked

    def add_trade(
        self,
        symbol,
        event_ms,
        *,
        price,
        quantity,
        buyer_is_maker,
    ):
        if symbol not in self.tracked_symbols or not isinstance(buyer_is_maker, bool):
            return False
        try:
            event_ms = _timestamp_ms(event_ms)
            notional = float(price) * float(quantity)
        except (TypeError, ValueError, OverflowError):
            return False
        if not isfinite(notional) or notional <= 0:
            return False

        events = self.events_by_symbol[symbol]
        if events and event_ms < events[-1][0]:
            return False
        signed_notional = -notional if buyer_is_maker else notional
        events.append((event_ms, signed_notional, notional))
        return True

    def snapshot(self, symbol, *, now_ms):
        if symbol not in self.tracked_symbols:
            return {"cvdStatus": "untracked"}

        now_ms = _timestamp_ms(now_ms)
        events = self.events_by_symbol[symbol]
        self._prune(events, now_ms)
        signed_notional = sum(event[1] for event in events)
        absolute_notional = sum(event[2] for event in events)
        ratio = signed_notional / absolute_notional if absolute_notional else 0.0
        complete = now_ms - self.coverage_started_at[symbol] >= self.coverage_ms
        return {
            "cvd15m": signed_notional,
            "cvd15mRatio": ratio,
            "cvdStatus": _status_for(ratio, complete),
            "cvdUpdatedAt": events[-1][0] if events else None,
        }

    def snapshots(self, *, now_ms):
        return {
            symbol: self.snapshot(symbol, now_ms=now_ms)
            for symbol in self.tracked_symbols
        }

    def _prune(self, events, now_ms):
        cutoff_ms = now_ms - self.window_ms
        while events and events[0][0] < cutoff_ms:
            events.popleft()


def _status_for(ratio, complete):
    if not complete:
        return "collecting"
    if ratio >= STATUS_THRESHOLD:
        return "buying"
    if ratio <= -STATUS_THRESHOLD:
        return "selling"
    return "neutral"


def _positive_milliseconds(seconds):
    try:
        parsed = float(seconds)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("duration must be a finite positive number") from exc
    if not isfinite(parsed) or parsed <= 0:
        raise ValueError("duration must be a finite positive number")
    return int(parsed * 1000)


def _timestamp_ms(value):
    if isinstance(value, bool):
        raise ValueError("timestamp must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("timestamp must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError("timestamp must be a non-negative integer")
    return parsed


def _is_symbol(value):
    return isinstance(value, str) and value and value == value.upper()
