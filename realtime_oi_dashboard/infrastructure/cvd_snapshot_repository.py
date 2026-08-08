"""Atomic JSON persistence for restart-safe CVD minute buckets."""

from __future__ import annotations

import json
import math
from pathlib import Path

from realtime_oi_dashboard.domain.cvd import MINUTE_MS
from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol
from realtime_oi_dashboard.infrastructure.file_io import write_text_atomic


CVD_SNAPSHOT_VERSION = 1
PERSIST_MINUTES = 20
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024


class CvdSnapshotRepository:
    def __init__(self, path: Path, *, persist_minutes=PERSIST_MINUTES) -> None:
        self.path = Path(path)
        self.persist_minutes = int(persist_minutes)

    def load(self, *, now_ms: int) -> tuple[dict[str, list[dict]], int | None]:
        if not self.path.exists():
            return {}, None
        raw = self.path.read_bytes()
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise ValueError("CVD snapshot is too large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise ValueError("unsupported CVD snapshot version")
        saved_at = payload.get("savedAt")
        if not isinstance(saved_at, int) or saved_at < 0:
            raise ValueError("invalid CVD snapshot timestamp")
        raw_symbols = payload.get("symbols")
        if not isinstance(raw_symbols, dict):
            raise ValueError("invalid CVD snapshot symbols")
        cutoff = (
            now_ms // MINUTE_MS * MINUTE_MS
            - self.persist_minutes * MINUTE_MS
        )
        records = {}
        for symbol, raw_buckets in raw_symbols.items():
            if not is_valid_binance_symbol(symbol) or not isinstance(raw_buckets, list):
                continue
            buckets = [
                bucket
                for bucket in raw_buckets
                if _valid_bucket(bucket, cutoff_ms=cutoff, now_ms=now_ms)
            ]
            if buckets:
                records[symbol] = buckets[-self.persist_minutes:]
        return records, saved_at

    def save(self, *, saved_at: int, symbols: dict[str, list[dict]]) -> None:
        payload = {
            "version": CVD_SNAPSHOT_VERSION,
            "savedAt": saved_at,
            "symbols": symbols,
        }
        text = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        if len(text.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ValueError("CVD snapshot is too large")
        write_text_atomic(self.path, text)


def _valid_bucket(value, *, cutoff_ms: int, now_ms: int) -> bool:
    if not isinstance(value, dict):
        return False
    try:
        open_time = int(value.get("openTime"))
        quote_volume = float(value.get("quoteVolume"))
        taker_buy = float(value.get("takerBuyQuoteVolume"))
    except (TypeError, ValueError, OverflowError):
        return False
    return (
        cutoff_ms <= open_time <= now_ms
        and open_time % MINUTE_MS == 0
        and math.isfinite(quote_volume)
        and math.isfinite(taker_buy)
        and quote_volume >= 0
        and 0 <= taker_buy <= quote_volume
        and isinstance(value.get("closed"), bool)
    )
