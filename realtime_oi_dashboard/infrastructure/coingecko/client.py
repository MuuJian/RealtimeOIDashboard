"""Refresh CoinGecko market caps in the background."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from math import isfinite
from pathlib import Path

from realtime_oi_dashboard.domain.errors import PollingStopped
from realtime_oi_dashboard.domain.market_cap import (
    build_market_cap_map,
    market_value_from_entry,
    normalize_ticker,
)
from realtime_oi_dashboard.infrastructure.coingecko.store import (
    load_market_cap_file,
    write_market_cap_file,
)
from realtime_oi_dashboard.domain.parsing import optional_int


COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_PAGE_COUNT = 8
COINGECKO_PER_PAGE = 250
COINGECKO_PAGE_DELAY_SECONDS = 30
COINGECKO_PAGE_FAILURE_ATTEMPTS = 3
COINGECKO_RETRY_BASE_SECONDS = 60
COINGECKO_RETRY_MAX_SECONDS = 5 * 60
DEFAULT_MARKET_CAP_REFRESH_SECONDS = 60 * 60


def _print_progress(message: str) -> None:
    print(message, flush=True)


class CoinGeckoMarketCapClient:
    """Refresh CoinGecko pages gradually while serving a JSON-backed snapshot."""

    def __init__(
        self,
        request_json: Callable[..., object],
        wait_for_retry: Callable[[float], None],
        record_error: Callable[[str, Exception], None],
        *,
        cache_seconds: float,
        store_path: Path,
        record_progress: Callable[[str], None] | None = None,
    ) -> None:
        self._request_json = request_json
        self._wait_for_retry = wait_for_retry
        self._record_error = record_error
        self._refresh_seconds = cache_seconds
        self._store_path = Path(store_path)
        self._record_progress = record_progress or _print_progress
        self._lock = threading.Lock()
        try:
            self._records = load_market_cap_file(self._store_path)
        except (OSError, ValueError, RecursionError) as exc:
            self._records = {}
            self._record_error("marketCapCache", exc)

    def get(self, active_symbols: set[str]) -> dict[str, dict[str, float]]:
        """Return last-known values without performing network I/O."""
        with self._lock:
            return {
                symbol: {"marketCap": self._records[symbol]["marketCap"]}
                for symbol in active_symbols
                if symbol in self._records
            }

    def count(self, active_symbols: set[str]) -> int:
        """Count active symbols with a last-known market cap."""
        with self._lock:
            return sum(symbol in self._records for symbol in active_symbols)

    def run_forever(
        self,
        active_symbols_provider: Callable[[], set[str]],
    ) -> None:
        """Refresh one page at a time until polling is stopped."""
        try:
            while True:
                active_symbols = active_symbols_provider()
                if not active_symbols:
                    self._wait_for_retry(1)
                    continue

                cycle_started = time.monotonic()
                failed_pages = []
                for page in range(1, COINGECKO_PAGE_COUNT + 1):
                    matched = self._refresh_page_with_retries(
                        page,
                        active_symbols,
                    )
                    loaded = self.count(active_symbols)
                    if matched is None:
                        failed_pages.append(page)
                        self._record_progress(
                            "CoinGecko market-cap page "
                            f"{page}/{COINGECKO_PAGE_COUNT} failed after "
                            f"{COINGECKO_PAGE_FAILURE_ATTEMPTS} attempts; "
                            f"loaded {loaded}/{len(active_symbols)} active symbols."
                        )
                    else:
                        self._record_progress(
                            "CoinGecko market-cap page "
                            f"{page}/{COINGECKO_PAGE_COUNT} succeeded; "
                            f"matched {matched}, loaded "
                            f"{loaded}/{len(active_symbols)} active symbols."
                        )
                    if page < COINGECKO_PAGE_COUNT:
                        self._wait_for_retry(COINGECKO_PAGE_DELAY_SECONDS)

                self._log_cycle_summary(active_symbols, failed_pages)

                elapsed = time.monotonic() - cycle_started
                next_cycle_delay = max(
                    self._refresh_seconds - elapsed,
                    COINGECKO_PAGE_DELAY_SECONDS,
                )
                self._wait_for_retry(next_cycle_delay)
        except PollingStopped:
            return

    def refresh_page(
        self,
        page: int,
        active_symbols: set[str],
    ) -> int:
        """Fetch and merge one ranked CoinGecko page."""
        response = self._request_json(
            COINGECKO_MARKETS_URL,
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": COINGECKO_PER_PAGE,
                "page": page,
            },
            timeout=12,
            attempts=1,
        )
        if not isinstance(response, list):
            raise ValueError("unexpected CoinGecko markets response")

        market_caps = build_market_cap_map(response, active_symbols)
        if not market_caps:
            return 0

        updated_at = time.time()
        source_records = _source_records(response)
        persistence_error = None
        with self._lock:
            merged_records = dict(self._records)
            for symbol, item in market_caps.items():
                incoming_record = {
                    "marketCap": item["marketCap"],
                    "updatedAt": updated_at,
                }
                source_record = source_records.get(normalize_ticker(symbol))
                if source_record is not None:
                    incoming_record.update(source_record)
                existing_record = merged_records.get(symbol)
                if _prefer_existing_record(existing_record, incoming_record):
                    continue
                merged_records[symbol] = incoming_record
            self._records = merged_records
            try:
                write_market_cap_file(
                    self._store_path,
                    self._records,
                    saved_at=updated_at,
                )
            except (OSError, TypeError, ValueError) as exc:
                persistence_error = exc

        if persistence_error is not None:
            self._record_error("marketCapCache", persistence_error)
        return len(market_caps)

    def _refresh_page_with_retries(
        self,
        page: int,
        active_symbols: set[str],
    ) -> int | None:
        for attempt in range(1, COINGECKO_PAGE_FAILURE_ATTEMPTS + 1):
            try:
                return self.refresh_page(page, active_symbols)
            except PollingStopped:
                raise
            except Exception as exc:
                self._record_error("marketCap", exc)
                if attempt == COINGECKO_PAGE_FAILURE_ATTEMPTS:
                    return None
                self._wait_for_retry(_retry_delay(attempt, exc))
        return None

    def _log_cycle_summary(
        self,
        active_symbols: set[str],
        failed_pages: list[int],
    ) -> None:
        with self._lock:
            loaded_symbols = active_symbols.intersection(self._records)
        missing_symbols = sorted(active_symbols.difference(loaded_symbols))
        status = "partial" if failed_pages else "complete"
        message = (
            f"CoinGecko market-cap refresh {status}; loaded "
            f"{len(loaded_symbols)}/{len(active_symbols)} active symbols"
        )
        if failed_pages:
            message += "; failed pages: " + ", ".join(map(str, failed_pages))
        if missing_symbols:
            message += "; missing: " + ", ".join(missing_symbols)
            if not failed_pages:
                message += " (not in top 2000 or ticker did not match)"
        else:
            message += "; no missing symbols"
        self._record_progress(message + ".")

    def retain_symbols(self, active_symbols: set[str]) -> None:
        """Remove confirmed inactive symbols from memory and the JSON file."""
        persistence_error = None
        with self._lock:
            retained = {
                symbol: record
                for symbol, record in self._records.items()
                if symbol in active_symbols
            }
            if retained == self._records:
                return
            self._records = retained
            saved_at = time.time()
            try:
                write_market_cap_file(
                    self._store_path,
                    self._records,
                    saved_at=saved_at,
                )
            except (OSError, TypeError, ValueError) as exc:
                persistence_error = exc
        if persistence_error is not None:
            self._record_error("marketCapCache", persistence_error)


def _retry_delay(attempt: int, exc: Exception) -> float:
    base_delay = min(
        COINGECKO_RETRY_BASE_SECONDS * (2 ** (attempt - 1)),
        COINGECKO_RETRY_MAX_SECONDS,
    )
    response = getattr(exc, "response", None)
    if response is None:
        return base_delay
    retry_after = response.headers.get("Retry-After")
    try:
        parsed_retry_after = float(retry_after)
    except (TypeError, ValueError):
        return base_delay
    if not isfinite(parsed_retry_after) or parsed_retry_after < 0:
        return base_delay
    return max(base_delay, parsed_retry_after)


def _source_records(markets: list[object]) -> dict[str, dict[str, object]]:
    records = {}
    for entry in markets:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        coingecko_id = entry.get("id")
        market_value = market_value_from_entry(entry)
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(coingecko_id, str)
            or not coingecko_id
            or market_value is None
        ):
            continue
        ticker = symbol.upper()
        if ticker in records:
            continue
        record: dict[str, object] = {"coingeckoId": coingecko_id}
        market_cap_rank = optional_int(entry.get("market_cap_rank"))
        if market_cap_rank is not None and market_cap_rank > 0:
            record["marketCapRank"] = market_cap_rank
        records[ticker] = record
    return records


def _prefer_existing_record(
    existing: dict[str, object] | None,
    incoming: dict[str, object],
) -> bool:
    if not existing:
        return False
    existing_id = existing.get("coingeckoId")
    incoming_id = incoming.get("coingeckoId")
    if not existing_id or not incoming_id or existing_id == incoming_id:
        return False
    existing_rank = optional_int(existing.get("marketCapRank"))
    incoming_rank = optional_int(incoming.get("marketCapRank"))
    if existing_rank is None:
        return incoming_rank is None
    if incoming_rank is None:
        return True
    return existing_rank < incoming_rank
