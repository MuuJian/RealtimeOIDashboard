"""Deterministic round-robin selection for OI polling batches."""

from __future__ import annotations


class RoundRobinBatchSelector:
    """Select a bounded batch while preserving the existing symbol order."""

    def __init__(self, batch_size: int) -> None:
        self.batch_size = batch_size
        self.position = 0

    def next_batch(self, symbols) -> list[str]:
        if not symbols:
            return []

        batch = []
        for _ in range(min(self.batch_size, len(symbols))):
            batch.append(symbols[self.position])
            self.position = (self.position + 1) % len(symbols)
        return batch

    def reset(self) -> None:
        self.position = 0

    def restore(self, position: int) -> None:
        self.position = position
