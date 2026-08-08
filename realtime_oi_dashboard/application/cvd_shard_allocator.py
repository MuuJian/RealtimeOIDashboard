"""Capacity and load-aware allocation for dynamically growing CVD shards."""

from __future__ import annotations

from math import ceil


TARGET_SYMBOLS_PER_SHARD = 150
TARGET_MESSAGES_PER_SECOND = 600.0
MAX_PROCESSING_LAG_MS = 500.0
SCALE_OUT_CONFIRM_SECONDS = 30.0


def desired_shard_count(
    symbol_count: int,
    *,
    target_symbols_per_shard: int = TARGET_SYMBOLS_PER_SHARD,
) -> int:
    if symbol_count <= 0:
        return 0
    return max(1, ceil(symbol_count / target_symbols_per_shard))


class CvdShardAllocator:
    def __init__(
        self,
        *,
        target_symbols_per_shard=TARGET_SYMBOLS_PER_SHARD,
        target_messages_per_second=TARGET_MESSAGES_PER_SECOND,
        max_processing_lag_ms=MAX_PROCESSING_LAG_MS,
        scale_out_confirm_seconds=SCALE_OUT_CONFIRM_SECONDS,
    ) -> None:
        self.target_symbols_per_shard = int(target_symbols_per_shard)
        self.target_messages_per_second = float(target_messages_per_second)
        self.max_processing_lag_ms = float(max_processing_lag_ms)
        self.scale_out_confirm_seconds = float(scale_out_confirm_seconds)
        self._assignments: dict[str, int] = {}
        self._overloaded_since: float | None = None

    def allocate(
        self,
        symbols: set[str],
        shard_count: int,
        *,
        message_rates: dict[str, float] | None = None,
    ) -> dict[int, set[str]]:
        if shard_count <= 0:
            self._assignments = {}
            return {}
        rates = message_rates or {}
        assignments = {index: set() for index in range(shard_count)}
        loads = {index: 0.0 for index in range(shard_count)}

        # Preserve valid assignments first to minimize subscription churn.
        for symbol in sorted(symbols):
            shard = self._assignments.get(symbol)
            if shard is None or shard >= shard_count:
                continue
            assignments[shard].add(symbol)
            loads[shard] += max(rates.get(symbol, 1.0), 0.01)

        unassigned = symbols.difference(self._assignments)
        unassigned.update(
            symbol
            for symbol, shard in self._assignments.items()
            if symbol in symbols and shard >= shard_count
        )
        for symbol in sorted(
            unassigned,
            key=lambda item: (-rates.get(item, 1.0), item),
        ):
            shard = min(
                assignments,
                key=lambda index: (
                    loads[index],
                    len(assignments[index]),
                    index,
                ),
            )
            assignments[shard].add(symbol)
            loads[shard] += max(rates.get(symbol, 1.0), 0.01)

        # When new shards are added, move symbols out of over-capacity shards
        # so scale-out actually distributes work instead of leaving them idle.
        balanced_size = ceil(len(symbols) / shard_count) if symbols else 0
        while any(len(items) > balanced_size for items in assignments.values()):
            source = max(assignments, key=lambda index: len(assignments[index]))
            target = min(
                assignments,
                key=lambda index: (len(assignments[index]), loads[index], index),
            )
            if source == target or len(assignments[source]) <= balanced_size:
                break
            symbol = max(
                assignments[source],
                key=lambda item: (rates.get(item, 1.0), item),
            )
            assignments[source].remove(symbol)
            assignments[target].add(symbol)
            symbol_load = max(rates.get(symbol, 1.0), 0.01)
            loads[source] -= symbol_load
            loads[target] += symbol_load

        self._assignments = {
            symbol: shard
            for shard, shard_symbols in assignments.items()
            for symbol in shard_symbols
        }
        return assignments

    def recommended_count(
        self,
        *,
        symbol_count: int,
        current_count: int,
        shard_metrics: list[dict],
        now: float,
    ) -> int:
        minimum = desired_shard_count(
            symbol_count,
            target_symbols_per_shard=self.target_symbols_per_shard,
        )
        overloaded = any(
            metric.get("symbolCount", 0) > self.target_symbols_per_shard
            or metric.get("messagesPerSecond", 0) > self.target_messages_per_second
            or metric.get("processingLagMs", 0) > self.max_processing_lag_ms
            or metric.get("queueDepth", 0) > 0
            for metric in shard_metrics
        )
        if not overloaded:
            self._overloaded_since = None
            return max(current_count, minimum)
        if self._overloaded_since is None:
            self._overloaded_since = now
            return max(current_count, minimum)
        if now - self._overloaded_since < self.scale_out_confirm_seconds:
            return max(current_count, minimum)
        self._overloaded_since = now
        return max(current_count + 1, minimum)
