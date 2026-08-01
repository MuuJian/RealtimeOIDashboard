"""CoinGecko market-cap loading with bounded stale-cache fallback."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.market_cache import MarketCache
from realtime_oi_dashboard.market_cap import build_market_cap_map


COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_PAGE_COUNT = 5
COINGECKO_PER_PAGE = 250
COINGECKO_PAGE_DELAY_SECONDS = 1.5
MARKET_CACHE_STALE_GRACE_SECONDS = 15 * 60


class CoinGeckoMarketCapClient:
    """Fetch the leading CoinGecko market pages and cache Binance mappings."""

    def __init__(
        self,
        request_json: Callable[..., object],
        wait_for_retry: Callable[[float], None],
        record_error: Callable[[str, Exception], None],
        *,
        cache_seconds: float,
    ) -> None:
        self._request_json = request_json
        self._wait_for_retry = wait_for_retry
        self._record_error = record_error
        self._lock = threading.Lock()
        self.cache = MarketCache(
            cache_seconds,
            MARKET_CACHE_STALE_GRACE_SECONDS,
        )

    def get(self, active_symbols: set[str]) -> dict[str, dict[str, float]]:
        now = time.monotonic()
        with self._lock:
            lookup = self.cache.get_fresh(now)
            if lookup.hit:
                return lookup.value

        markets, page_error = self._fetch_pages()
        if not markets:
            return self._fallback_after_failure(page_error)

        if page_error is not None:
            # Keep successfully fetched pages when a later page is rate-limited.
            self._record_error("marketCap", page_error)

        response_time = time.monotonic()
        market_caps = build_market_cap_map(markets, active_symbols)
        with self._lock:
            self.cache.store(
                market_caps,
                response_time,
                self.cache.cache_seconds,
            )
        return market_caps

    def _fetch_pages(self) -> tuple[list, Exception | None]:
        markets = []
        page_error = None
        for page in range(1, COINGECKO_PAGE_COUNT + 1):
            try:
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
            except PollingStopped:
                raise
            except Exception as exc:
                page_error = exc
                break

            markets.extend(response)
            if page < COINGECKO_PAGE_COUNT:
                self._wait_for_retry(COINGECKO_PAGE_DELAY_SECONDS)
        return markets, page_error

    def _fallback_after_failure(
        self,
        page_error: Exception | None,
    ) -> dict[str, dict[str, float]]:
        failure_time = time.monotonic()
        with self._lock:
            fallback = self.cache.fallback_after_failure(
                failure_time,
                self.cache.cache_seconds,
                throttle_without_value=True,
            )
        self._record_error(
            "marketCap",
            page_error or ValueError("no CoinGecko market-cap pages fetched"),
        )
        return fallback.value if fallback.hit else {}

    def clear(self) -> None:
        with self._lock:
            self.cache.clear()
