"""Persistent validation and atomic writes for CoinGecko market-cap data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from realtime_oi_dashboard.infrastructure.file_io import write_text_atomic
from realtime_oi_dashboard.domain.parsing import optional_float, optional_int
from realtime_oi_dashboard.domain.symbols import is_valid_binance_symbol


MARKET_CAP_SCHEMA_VERSION = 1
MAX_MARKET_CAP_FILE_BYTES = 2 * 1024 * 1024


def load_market_cap_file(path: Path) -> dict[str, dict[str, Any]]:
    """Load valid last-known market caps from *path*."""
    if not path.exists():
        return {}

    payload = json.loads(_read_market_cap_text(path))
    if not isinstance(payload, dict):
        return {}
    raw_records = payload.get("market_caps")
    if not isinstance(raw_records, dict):
        return {}

    records: dict[str, dict[str, Any]] = {}
    for symbol, item in raw_records.items():
        if not is_valid_binance_symbol(symbol) or not isinstance(item, dict):
            continue
        market_cap = optional_float(item.get("marketCap"))
        updated_at = optional_float(item.get("updatedAt"))
        if market_cap is None or market_cap <= 0:
            continue
        record = {"marketCap": market_cap}
        if updated_at is not None and updated_at >= 0:
            record["updatedAt"] = updated_at
        coingecko_id = item.get("coingeckoId")
        if isinstance(coingecko_id, str) and coingecko_id:
            record["coingeckoId"] = coingecko_id
        market_cap_rank = optional_int(item.get("marketCapRank"))
        if market_cap_rank is not None and market_cap_rank > 0:
            record["marketCapRank"] = market_cap_rank
        records[symbol] = record
    return records


def write_market_cap_file(
    path: Path,
    records: dict[str, dict[str, Any]],
    *,
    saved_at: float,
) -> None:
    """Atomically serialize the last-known market caps."""
    payload = {
        "schema_version": MARKET_CAP_SCHEMA_VERSION,
        "saved_at": saved_at,
        "market_caps": {
            symbol: records[symbol]
            for symbol in sorted(records)
        },
    }
    text = json.dumps(payload, ensure_ascii=False, allow_nan=False)
    if len(text.encode("utf-8")) > MAX_MARKET_CAP_FILE_BYTES:
        raise ValueError(
            f"market-cap cache exceeds {MAX_MARKET_CAP_FILE_BYTES} bytes"
        )
    write_text_atomic(path, text)


def _read_market_cap_text(path: Path) -> str:
    with path.open("rb") as file:
        raw_payload = file.read(MAX_MARKET_CAP_FILE_BYTES + 1)
    if len(raw_payload) > MAX_MARKET_CAP_FILE_BYTES:
        raise ValueError(
            f"market-cap cache exceeds {MAX_MARKET_CAP_FILE_BYTES} bytes"
        )
    return raw_payload.decode("utf-8")
