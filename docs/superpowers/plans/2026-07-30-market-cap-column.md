# Market Cap Column Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sortable "市值" (market cap) column to the main "OI 变化排行" ranking table, backed by a new CoinGecko-fed server-side cache, without touching the "7D OI 异动信号" table.

**Architecture:** A new `market_cap.py` module does pure, network-free ticker normalization + matching. `BinanceFuturesClient` gets a new `get_market_caps()` method that fetches CoinGecko's top-500-by-market-cap list through the existing `MarketCache` (same stale-serving pattern already used for funding rates), keyed by Binance symbol. `OIPoller` threads the resulting map through its existing per-batch data flow (`tickers` / `funding_rates` already flow this way) into each row as `marketCap`. The frontend adds an optional cell to the shared row-cell builder (so the signal table is unaffected), a new sortable column, and bumps the schema-version guard that already exists between backend and frontend.

**Tech Stack:** Python 3.11 stdlib + `requests` (already a dependency, no new packages), vanilla JS ES modules (no build step, no new packages).

## Global Constraints

- Python 3.10+ (per repo README) — this repo runs on 3.11 locally/on Railway.
- No new dependencies. CoinGecko is called through the existing `requests`-based `JsonHttpClient`; no `pytest` — write tests with stdlib `unittest` since the repo has zero existing test infrastructure to follow.
- UI copy stays Simplified Chinese, consistent with the rest of the dashboard: the column header is "市值".
- Market cap is added ONLY to the main ranking table (`.oi-table` / "OI 变化排行"). The "7D OI 异动信号" table (`HighOi7dTable.js`) is explicitly NOT touched — this was a user-approved design decision.
- `poller.py`'s `OI_API_SCHEMA_VERSION` and `useOiRankingData.js`'s `OI_API_SCHEMA_VERSION` are a matched pair — the frontend hard-rejects any payload where they don't match (`useOiRankingData.js:115`). Both MUST be bumped together (5 → 6) in the same task, or the dashboard will silently stop rendering entirely.
- This is a local-only patch on top of a cloned upstream repo (`MuuJian/RealtimeOIDashboard`) with no push access — do not attempt to open a PR upstream.
- Symbol matching is intentionally best-effort (per approved design): no manual override table. A Binance symbol that doesn't match any CoinGecko ticker after normalization simply gets no `marketCap` (renders as `-`). This is expected behavior, not a bug to fix.

---

### Task 1: Symbol normalization + CoinGecko matching (pure, unit-tested)

**Files:**
- Create: `realtime_oi_dashboard/market_cap.py`
- Test: `tests/test_market_cap.py`

**Interfaces:**
- Produces: `normalize_ticker(binance_symbol: str) -> str`, `build_market_cap_map(coingecko_markets: list, active_symbols: set[str]) -> dict[str, dict[str, float]]` — both pure functions, no I/O. Task 2 imports `build_market_cap_map` from this module.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_market_cap.py`:

```python
import unittest

from realtime_oi_dashboard.market_cap import build_market_cap_map, normalize_ticker


class NormalizeTickerTests(unittest.TestCase):
    def test_strips_1000_prefix(self):
        self.assertEqual(normalize_ticker("1000PEPEUSDT"), "PEPE")

    def test_strips_1000000_prefix(self):
        self.assertEqual(normalize_ticker("1000000BOBUSDT"), "BOB")

    def test_strips_1m_prefix(self):
        self.assertEqual(normalize_ticker("1MBABYDOGEUSDT"), "BABYDOGE")

    def test_plain_symbol_unchanged_besides_quote_strip(self):
        self.assertEqual(normalize_ticker("BTCUSDT"), "BTC")

    def test_1inch_is_not_treated_as_multiplier_prefixed(self):
        # 1INCH is a real project ticker, not a "1000x contract" symbol.
        self.assertEqual(normalize_ticker("1INCHUSDT"), "1INCH")


class BuildMarketCapMapTests(unittest.TestCase):
    def test_matches_by_normalized_ticker(self):
        markets = [
            {"symbol": "btc", "market_cap": 900000000000},
            {"symbol": "pepe", "market_cap": 5000000000},
        ]
        active_symbols = {"BTCUSDT", "1000PEPEUSDT", "UNMATCHEDUSDT"}

        result = build_market_cap_map(markets, active_symbols)

        self.assertEqual(result["BTCUSDT"]["marketCap"], 900000000000)
        self.assertEqual(result["1000PEPEUSDT"]["marketCap"], 5000000000)
        self.assertNotIn("UNMATCHEDUSDT", result)

    def test_first_entry_wins_on_ticker_collision(self):
        # CoinGecko is requested with order=market_cap_desc, so the first
        # entry for a given ticker is the higher-market-cap one.
        markets = [
            {"symbol": "abc", "market_cap": 100},
            {"symbol": "abc", "market_cap": 1},
        ]
        active_symbols = {"ABCUSDT"}

        result = build_market_cap_map(markets, active_symbols)

        self.assertEqual(result["ABCUSDT"]["marketCap"], 100)

    def test_skips_malformed_entries_without_raising(self):
        markets = [
            {"symbol": "btc"},  # missing market_cap
            {"market_cap": 500},  # missing symbol
            "not-a-dict",
            {"symbol": "eth", "market_cap": 300000000000},
        ]
        active_symbols = {"BTCUSDT", "ETHUSDT"}

        result = build_market_cap_map(markets, active_symbols)

        self.assertNotIn("BTCUSDT", result)
        self.assertEqual(result["ETHUSDT"]["marketCap"], 300000000000)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest tests.test_market_cap -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'realtime_oi_dashboard.market_cap'`

- [ ] **Step 3: Write the implementation**

Create `realtime_oi_dashboard/market_cap.py`:

```python
"""Best-effort matching between Binance futures symbols and CoinGecko tickers."""

from __future__ import annotations

from typing import Any

from realtime_oi_dashboard.parsing import optional_float

# Order matters: try the longest/most specific prefix first. "1INCH" must
# NOT be caught here — it's a real project ticker, not a multiplier contract.
MULTIPLIER_PREFIXES = ("1000000", "1000", "1M")
QUOTE_ASSET = "USDT"


def normalize_ticker(binance_symbol: str) -> str:
    """Map a Binance perpetual symbol onto the ticker CoinGecko likely uses."""
    base = binance_symbol
    if base.endswith(QUOTE_ASSET):
        base = base[: -len(QUOTE_ASSET)]
    for prefix in MULTIPLIER_PREFIXES:
        if base.startswith(prefix) and len(base) > len(prefix):
            base = base[len(prefix):]
            break
    return base.upper()


def build_market_cap_map(
    coingecko_markets: list[Any],
    active_symbols: set[str],
) -> dict[str, dict[str, float]]:
    """Build a {binance_symbol: {"marketCap": value}} map for active symbols.

    `coingecko_markets` should be in market-cap-descending order (the caller
    requests CoinGecko's `/coins/markets` with `order=market_cap_desc`), so
    when multiple coins share a ticker, the first one seen is the one with
    the larger market cap.
    """
    ticker_to_market_cap: dict[str, float] = {}
    for entry in coingecko_markets:
        if not isinstance(entry, dict):
            continue
        symbol = entry.get("symbol")
        if not isinstance(symbol, str) or not symbol:
            continue
        market_cap = optional_float(entry.get("market_cap"))
        if market_cap is None or market_cap <= 0:
            continue
        ticker = symbol.upper()
        if ticker not in ticker_to_market_cap:
            ticker_to_market_cap[ticker] = market_cap

    result: dict[str, dict[str, float]] = {}
    for binance_symbol in active_symbols:
        market_cap = ticker_to_market_cap.get(normalize_ticker(binance_symbol))
        if market_cap is not None:
            result[binance_symbol] = {"marketCap": market_cap}
    return result
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest tests.test_market_cap -v`
Expected: all 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add realtime_oi_dashboard/market_cap.py tests/test_market_cap.py
git commit -m "Add Binance-to-CoinGecko ticker matching for market cap"
```

---

### Task 2: `BinanceFuturesClient.get_market_caps()`

**Files:**
- Modify: `realtime_oi_dashboard/binance_client.py`

**Interfaces:**
- Consumes: `build_market_cap_map(coingecko_markets, active_symbols)` from Task 1; `MarketCache` (existing class, unmodified); `self.http_client.get_json(url, params=..., timeout=..., attempts=...)` (existing, unmodified); `self.record_error(source: str, exc: Exception)` (existing).
- Produces: constructor param `market_cap_cache_seconds: float`; method `get_market_caps(self, active_symbols: set[str]) -> dict[str, dict[str, float]]`. Task 3 (`poller.py`) calls this method and passes its constructor param through.

This task has no isolated unit test (it's a thin network-calling wrapper around already-tested `build_market_cap_map` and already-tested `MarketCache`); it's verified by the manual end-to-end check in Task 9. Follow the steps exactly — this mirrors the existing `get_funding_rates` method one-for-one.

- [ ] **Step 1: Add the constructor param and cache instance**

In `realtime_oi_dashboard/binance_client.py`, find this block near the top of the file:

```python
PARTIAL_RESPONSE_RETRY_SECONDS = 60
MARKET_CACHE_STALE_GRACE_SECONDS = 15 * 60
```

Replace it with:

```python
PARTIAL_RESPONSE_RETRY_SECONDS = 60
MARKET_CACHE_STALE_GRACE_SECONDS = 15 * 60
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_PAGE_COUNT = 2
COINGECKO_PER_PAGE = 250
```

Find the constructor signature:

```python
    def __init__(
        self,
        stop_event: threading.Event,
        record_error: Callable[[str, Exception], None],
        *,
        oi_history_cache_seconds: float,
        ticker_cache_seconds: float,
        funding_cache_seconds: float,
        http_client=None,
    ) -> None:
```

Replace it with:

```python
    def __init__(
        self,
        stop_event: threading.Event,
        record_error: Callable[[str, Exception], None],
        *,
        oi_history_cache_seconds: float,
        ticker_cache_seconds: float,
        funding_cache_seconds: float,
        market_cap_cache_seconds: float = 900,
        http_client=None,
    ) -> None:
```

Find:

```python
        self.funding_cache = MarketCache(
            funding_cache_seconds,
            MARKET_CACHE_STALE_GRACE_SECONDS,
        )
        self.oi_history = OiHistoryService(
```

Replace with:

```python
        self.funding_cache = MarketCache(
            funding_cache_seconds,
            MARKET_CACHE_STALE_GRACE_SECONDS,
        )
        self.market_cap_cache = MarketCache(
            market_cap_cache_seconds,
            MARKET_CACHE_STALE_GRACE_SECONDS,
        )
        self.oi_history = OiHistoryService(
```

- [ ] **Step 2: Add the import**

Find:

```python
from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.market_cache import MarketCache
```

Replace with:

```python
from realtime_oi_dashboard.errors import PollingStopped
from realtime_oi_dashboard.market_cache import MarketCache
from realtime_oi_dashboard.market_cap import build_market_cap_map
```

- [ ] **Step 3: Add the `get_market_caps` method**

Find the end of `get_funding_rates` and the start of `_next_funding_refresh_at`:

```python
        return funding_rates

    def _next_funding_refresh_at(
```

Replace with:

```python
        return funding_rates

    def get_market_caps(
        self,
        active_symbols: set[str],
    ) -> dict[str, dict[str, float]]:
        now = time.monotonic()
        with self.market_cache_lock:
            lookup = self.market_cap_cache.get_fresh(now)
            if lookup.hit:
                return lookup.value

        try:
            markets: list = []
            for page in range(1, COINGECKO_PAGE_COUNT + 1):
                response = self.request_json(
                    COINGECKO_MARKETS_URL,
                    params={
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": COINGECKO_PER_PAGE,
                        "page": page,
                    },
                    timeout=12,
                )
                if not isinstance(response, list):
                    raise ValueError("unexpected CoinGecko markets response")
                markets.extend(response)
            response_time = time.monotonic()
            market_caps = build_market_cap_map(markets, active_symbols)
        except PollingStopped:
            raise
        except Exception as exc:
            failure_time = time.monotonic()
            with self.market_cache_lock:
                fallback = self.market_cap_cache.fallback_after_failure(
                    failure_time,
                    min(
                        self.market_cap_cache.cache_seconds,
                        PARTIAL_RESPONSE_RETRY_SECONDS,
                    ),
                    throttle_without_value=True,
                )
            self.record_error("marketCap", exc)
            return fallback.value if fallback.hit else {}

        with self.market_cache_lock:
            self.market_cap_cache.store(
                market_caps,
                response_time,
                self.market_cap_cache.cache_seconds,
            )
        return market_caps

    def _next_funding_refresh_at(
```

- [ ] **Step 4: Include the new cache in `clear_caches`**

Find:

```python
    def clear_caches(self) -> None:
        self.oi_history.clear()
        with self.market_cache_lock:
            self.ticker_cache.clear()
            self.funding_cache.clear()
```

Replace with:

```python
    def clear_caches(self) -> None:
        self.oi_history.clear()
        with self.market_cache_lock:
            self.ticker_cache.clear()
            self.funding_cache.clear()
            self.market_cap_cache.clear()
```

(Deliberately NOT added to `retain_symbols` — the market-cap cache holds CoinGecko's global top-500 list, not a per-active-symbol response, so pruning it when symbols change would just force an unnecessary refetch for no benefit.)

- [ ] **Step 5: Sanity-check the module still imports cleanly**

Run: `python -c "import realtime_oi_dashboard.binance_client"`
Expected: no output, exit code 0 (import succeeds)

- [ ] **Step 6: Commit**

```bash
git add realtime_oi_dashboard/binance_client.py
git commit -m "Add CoinGecko-backed get_market_caps to BinanceFuturesClient"
```

---

### Task 3: Wire market caps through `OIPoller` into each row

**Files:**
- Modify: `realtime_oi_dashboard/poller.py`

**Interfaces:**
- Consumes: `BinanceFuturesClient(..., market_cap_cache_seconds=...)` and `self.binance.get_market_caps(active_symbols)` from Task 2.
- Produces: `OIPoller.__init__(..., market_cap_cache_seconds=900, ...)`; row dicts now include `"marketCap": float | None`. Task 4 (`server.py`) passes its new CLI value into this constructor param. Task 5 (frontend) relies on the row having a `marketCap` key and on `OI_API_SCHEMA_VERSION == 6`.

- [ ] **Step 1: Bump the schema version**

Find:

```python
OI_API_SCHEMA_VERSION = 5
```

Replace with:

```python
OI_API_SCHEMA_VERSION = 6
```

- [ ] **Step 2: Add the constructor parameter**

Find:

```python
    def __init__(
        self,
        batch_size=25,
        batch_delay=1.0,
        oi_workers=3,
        refresh_symbols_interval=900,
        oi_history_cache_seconds=300,
        ticker_cache_seconds=10,
        funding_cache_seconds=3600,
        snapshot_save_interval=10,
        snapshot_file=None,
        http_client=None,
    ):
```

Replace with:

```python
    def __init__(
        self,
        batch_size=25,
        batch_delay=1.0,
        oi_workers=3,
        refresh_symbols_interval=900,
        oi_history_cache_seconds=300,
        ticker_cache_seconds=10,
        funding_cache_seconds=3600,
        market_cap_cache_seconds=900,
        snapshot_save_interval=10,
        snapshot_file=None,
        http_client=None,
    ):
```

Find:

```python
        funding_cache_seconds = _non_negative_seconds(
            "funding_cache_seconds",
            funding_cache_seconds,
        )
        self.snapshot_save_interval = _non_negative_seconds(
```

Replace with:

```python
        funding_cache_seconds = _non_negative_seconds(
            "funding_cache_seconds",
            funding_cache_seconds,
        )
        market_cap_cache_seconds = _non_negative_seconds(
            "market_cap_cache_seconds",
            market_cap_cache_seconds,
        )
        self.snapshot_save_interval = _non_negative_seconds(
```

Find:

```python
        self.binance = BinanceFuturesClient(
            self.stop_event,
            self.record_symbol_error,
            oi_history_cache_seconds=oi_history_cache_seconds,
            ticker_cache_seconds=ticker_cache_seconds,
            funding_cache_seconds=funding_cache_seconds,
            http_client=http_client,
        )
```

Replace with:

```python
        self.binance = BinanceFuturesClient(
            self.stop_event,
            self.record_symbol_error,
            oi_history_cache_seconds=oi_history_cache_seconds,
            ticker_cache_seconds=ticker_cache_seconds,
            funding_cache_seconds=funding_cache_seconds,
            market_cap_cache_seconds=market_cap_cache_seconds,
            http_client=http_client,
        )
```

- [ ] **Step 3: Add the `get_market_caps` passthrough method**

Find:

```python
    def get_funding_rates(self):
        with self.lock:
            active_symbols = set(self.symbols)
        return self.binance.get_funding_rates(active_symbols)

    def get_open_interest(self, symbol):
```

Replace with:

```python
    def get_funding_rates(self):
        with self.lock:
            active_symbols = set(self.symbols)
        return self.binance.get_funding_rates(active_symbols)

    def get_market_caps(self):
        with self.lock:
            active_symbols = set(self.symbols)
        return self.binance.get_market_caps(active_symbols)

    def get_open_interest(self, symbol):
```

- [ ] **Step 4: Fetch market caps once per batch and thread them through**

Find:

```python
        tickers = self.get_market_tickers()
        if self.stop_event.is_set():
            return
        funding_rates = self.get_funding_rates()
        if self.stop_event.is_set():
            return
        batch_start = self.symbol_index
        batch = self.next_batch()
        if not batch:
            return
        try:
            results = self.update_symbols(
                batch,
                tickers,
                funding_rates,
                executor=executor,
            )
```

Replace with:

```python
        tickers = self.get_market_tickers()
        if self.stop_event.is_set():
            return
        funding_rates = self.get_funding_rates()
        if self.stop_event.is_set():
            return
        market_caps = self.get_market_caps()
        if self.stop_event.is_set():
            return
        batch_start = self.symbol_index
        batch = self.next_batch()
        if not batch:
            return
        try:
            results = self.update_symbols(
                batch,
                tickers,
                funding_rates,
                market_caps,
                executor=executor,
            )
```

- [ ] **Step 5: Thread `market_caps` through `update_symbols` / `_update_symbols_parallel`**

Find:

```python
    def update_symbols(self, batch, tickers, funding_rates, executor=None):
        if self.oi_workers <= 1 or len(batch) <= 1:
            results = []
            for symbol in batch:
                if self.stop_event.is_set():
                    break
                try:
                    results.append(self.build_symbol_update(symbol, tickers, funding_rates))
                except PollingStopped:
                    break
                except Exception as exc:
                    self.record_symbol_error(symbol, exc)
                    results.append(None)
            return results

        if executor is not None:
            return self._update_symbols_parallel(batch, tickers, funding_rates, executor)

        max_workers = min(self.oi_workers, len(batch))
        with ThreadPoolExecutor(max_workers=max_workers) as temporary_executor:
            return self._update_symbols_parallel(
                batch,
                tickers,
                funding_rates,
                temporary_executor,
            )

    def _update_symbols_parallel(self, batch, tickers, funding_rates, executor):
        futures = {}
        try:
            for symbol in batch:
                future = executor.submit(
                    self.build_symbol_update,
                    symbol,
                    tickers,
                    funding_rates,
                )
                futures[future] = symbol
```

Replace with:

```python
    def update_symbols(self, batch, tickers, funding_rates, market_caps, executor=None):
        if self.oi_workers <= 1 or len(batch) <= 1:
            results = []
            for symbol in batch:
                if self.stop_event.is_set():
                    break
                try:
                    results.append(
                        self.build_symbol_update(symbol, tickers, funding_rates, market_caps)
                    )
                except PollingStopped:
                    break
                except Exception as exc:
                    self.record_symbol_error(symbol, exc)
                    results.append(None)
            return results

        if executor is not None:
            return self._update_symbols_parallel(
                batch, tickers, funding_rates, market_caps, executor
            )

        max_workers = min(self.oi_workers, len(batch))
        with ThreadPoolExecutor(max_workers=max_workers) as temporary_executor:
            return self._update_symbols_parallel(
                batch,
                tickers,
                funding_rates,
                market_caps,
                temporary_executor,
            )

    def _update_symbols_parallel(self, batch, tickers, funding_rates, market_caps, executor):
        futures = {}
        try:
            for symbol in batch:
                future = executor.submit(
                    self.build_symbol_update,
                    symbol,
                    tickers,
                    funding_rates,
                    market_caps,
                )
                futures[future] = symbol
```

- [ ] **Step 6: Add `marketCap` to the row in `build_symbol_update`**

Find:

```python
    def build_symbol_update(self, symbol, tickers, funding_rates):
        if self.stop_event.is_set():
            return None

        ticker = tickers.get(symbol)
        if not ticker:
            raise ValueError("ticker data unavailable")
        price = ticker["price"]
        volume_24h = ticker["volume24h"]
```

Replace with:

```python
    def build_symbol_update(self, symbol, tickers, funding_rates, market_caps=None):
        if self.stop_event.is_set():
            return None

        ticker = tickers.get(symbol)
        if not ticker:
            raise ValueError("ticker data unavailable")
        price = ticker["price"]
        volume_24h = ticker["volume24h"]
```

Find:

```python
        row = {
            "symbol": symbol,
            "price": price,
            "volume24h": volume_24h,
            "currentOi": current_oi,
            "currentOiValue": current_oi_value,
            "oiUpdatedAt": now_ms,
            "priceChangePercent": ticker.get("priceChangePercent"),
            "fundingRatePercent": funding_rate_percent,
            "nextFundingTime": next_funding_time,
            **oi_history,
        }
```

Replace with:

```python
        market_cap = (market_caps or {}).get(symbol, {}).get("marketCap")

        row = {
            "symbol": symbol,
            "price": price,
            "volume24h": volume_24h,
            "currentOi": current_oi,
            "currentOiValue": current_oi_value,
            "marketCap": market_cap,
            "oiUpdatedAt": now_ms,
            "priceChangePercent": ticker.get("priceChangePercent"),
            "fundingRatePercent": funding_rate_percent,
            "nextFundingTime": next_funding_time,
            **oi_history,
        }
```

- [ ] **Step 7: Sanity-check the module still imports cleanly**

Run: `python -c "import realtime_oi_dashboard.poller"`
Expected: no output, exit code 0

- [ ] **Step 8: Commit**

```bash
git add realtime_oi_dashboard/poller.py
git commit -m "Thread market caps through the OI poller into each row; bump schema to v6"
```

---

### Task 4: `server.py` CLI flag

**Files:**
- Modify: `realtime_oi_dashboard/server.py`

**Interfaces:**
- Consumes: `OIPoller(..., market_cap_cache_seconds=...)` from Task 3.
- Produces: new CLI flag `--market-cap-cache-seconds` (default `900`), so hosting environments (Railway included) can tune it without a code change, matching `--funding-cache-seconds`.

- [ ] **Step 1: Add the CLI argument**

Find:

```python
    parser.add_argument(
        "--funding-cache-seconds",
        type=non_negative_float,
        default=3600,
        help="fallback funding-rate cache duration; 0 disables the cache",
    )
    parser.add_argument(
        "--snapshot-save-interval",
```

Replace with:

```python
    parser.add_argument(
        "--funding-cache-seconds",
        type=non_negative_float,
        default=3600,
        help="fallback funding-rate cache duration; 0 disables the cache",
    )
    parser.add_argument(
        "--market-cap-cache-seconds",
        type=non_negative_float,
        default=900,
        help="market-cap cache duration (CoinGecko); 0 disables the cache",
    )
    parser.add_argument(
        "--snapshot-save-interval",
```

- [ ] **Step 2: Pass it to `OIPoller`**

Find:

```python
    poller = OIPoller(
        batch_size=args.oi_batch_size,
        batch_delay=args.oi_batch_delay,
        oi_workers=args.oi_workers,
        oi_history_cache_seconds=args.oi_history_cache_seconds,
        ticker_cache_seconds=args.ticker_cache_seconds,
        funding_cache_seconds=args.funding_cache_seconds,
        snapshot_save_interval=args.snapshot_save_interval,
    )
```

Replace with:

```python
    poller = OIPoller(
        batch_size=args.oi_batch_size,
        batch_delay=args.oi_batch_delay,
        oi_workers=args.oi_workers,
        oi_history_cache_seconds=args.oi_history_cache_seconds,
        ticker_cache_seconds=args.ticker_cache_seconds,
        funding_cache_seconds=args.funding_cache_seconds,
        market_cap_cache_seconds=args.market_cap_cache_seconds,
        snapshot_save_interval=args.snapshot_save_interval,
    )
```

- [ ] **Step 3: Verify `--help` shows the new flag**

Run: `python main.py --help`
Expected: output includes a `--market-cap-cache-seconds` line with the help text from Step 1

- [ ] **Step 4: Commit**

```bash
git add realtime_oi_dashboard/server.py
git commit -m "Add --market-cap-cache-seconds CLI flag"
```

---

### Task 5: Frontend schema version bump + sort key

**Files:**
- Modify: `realtime_oi_dashboard/static/js/hooks/useOiRankingData.js`
- Modify: `realtime_oi_dashboard/static/js/hooks/useTableSort.js`

**Interfaces:**
- Consumes: backend now sends `schema_version: 6` and rows with a `marketCap` field (Task 3).
- Produces: frontend accepts the v6 payload; `"marketCap"` is now a valid value for `sort.setSort()` / `sort.setSortKey()`, which Task 6/7 rely on for the new column header and dropdown option.

- [ ] **Step 1: Bump the frontend schema constant**

In `realtime_oi_dashboard/static/js/hooks/useOiRankingData.js`, find:

```javascript
const OI_API_SCHEMA_VERSION = 5;
```

Replace with:

```javascript
const OI_API_SCHEMA_VERSION = 6;
```

- [ ] **Step 2: Add `marketCap` as a valid sort key**

In `realtime_oi_dashboard/static/js/hooks/useTableSort.js`, find:

```javascript
const VALID_SORT_KEYS = new Set([
  "symbol",
  "price",
  "fundingRatePercent",
  "priceChangePercent",
  "price7dChangePercent",
  "currentOiValue",
  "volume24h",
  "oi24hChangePercent",
  "oi7dChangePercent",
]);
```

Replace with:

```javascript
const VALID_SORT_KEYS = new Set([
  "symbol",
  "price",
  "fundingRatePercent",
  "priceChangePercent",
  "price7dChangePercent",
  "currentOiValue",
  "marketCap",
  "volume24h",
  "oi24hChangePercent",
  "oi7dChangePercent",
]);
```

- [ ] **Step 3: Check the JS syntax checker still passes**

Run: `node realtime_oi_dashboard/scripts/check-static-js.mjs`
Expected: exits 0 with no errors reported (this script checks JS syntax, relative imports, entry reachability, style entry point, and page IDs — see the repo README)

- [ ] **Step 4: Commit**

```bash
git add realtime_oi_dashboard/static/js/hooks/useOiRankingData.js realtime_oi_dashboard/static/js/hooks/useTableSort.js
git commit -m "Bump OI API schema to v6 and allow sorting by marketCap"
```

---

### Task 6: Optional market-cap cell in the shared row-cell builder

**Files:**
- Modify: `realtime_oi_dashboard/static/js/components/MarketRowCells.js`
- Modify: `realtime_oi_dashboard/static/js/components/OiRankingRow.js`

**Interfaces:**
- Consumes: `formatCurrency` from `../utils/format.js` (existing, unmodified — it already renders large USD values compactly with 万/亿 units, exactly what market cap needs).
- Produces: `createMarketRowCells({ includeMarketCap: true })` — new optional param, default `false`. When `true`, `orderedCells` gains one extra `<td>` positioned right after the OI-value cell, and the returned object gains a `marketCapCell` property. `HighOi7dTable.js` is NOT modified — it keeps calling `createMarketRowCells()` with no args, so the signal table is unaffected (verify this by inspection in Step 4, don't edit the file).

- [ ] **Step 1: Make the market-cap cell optional in `createMarketRowCells`**

In `realtime_oi_dashboard/static/js/components/MarketRowCells.js`, find:

```javascript
export function createMarketRowCells() {
  const symbolCell = document.createElement("td");
  symbolCell.className = "symbol";
  const symbolLink = createLink();
  symbolCell.append(symbolLink);

  const priceCell = document.createElement("td");
  const priceLink = createLink();
  priceCell.append(priceLink);

  const fundingRateCell = document.createElement("td");
  const priceChangeCell = document.createElement("td");
  const price7dChangeCell = document.createElement("td");
  const oiValueCell = document.createElement("td");
  const volumeCell = document.createElement("td");
  const oi24hChangeCell = document.createElement("td");
  const oi7dChangeCell = document.createElement("td");
  const oiUpdatedAtCell = createOiUpdateSignalCell();

  return {
    orderedCells: [
      symbolCell,
      priceCell,
      fundingRateCell,
      priceChangeCell,
      price7dChangeCell,
      oiValueCell,
      volumeCell,
      oi24hChangeCell,
      oi7dChangeCell,
      oiUpdatedAtCell,
    ],
    symbolLink,
    priceLink,
    fundingRateCell,
    priceChangeCell,
    price7dChangeCell,
    oiValueCell,
    volumeCell,
    oi24hChangeCell,
    oi7dChangeCell,
    oiUpdatedAtCell,
  };
}
```

Replace with:

```javascript
export function createMarketRowCells({ includeMarketCap = false } = {}) {
  const symbolCell = document.createElement("td");
  symbolCell.className = "symbol";
  const symbolLink = createLink();
  symbolCell.append(symbolLink);

  const priceCell = document.createElement("td");
  const priceLink = createLink();
  priceCell.append(priceLink);

  const fundingRateCell = document.createElement("td");
  const priceChangeCell = document.createElement("td");
  const price7dChangeCell = document.createElement("td");
  const oiValueCell = document.createElement("td");
  const marketCapCell = includeMarketCap ? document.createElement("td") : null;
  const volumeCell = document.createElement("td");
  const oi24hChangeCell = document.createElement("td");
  const oi7dChangeCell = document.createElement("td");
  const oiUpdatedAtCell = createOiUpdateSignalCell();

  return {
    orderedCells: [
      symbolCell,
      priceCell,
      fundingRateCell,
      priceChangeCell,
      price7dChangeCell,
      oiValueCell,
      ...(marketCapCell ? [marketCapCell] : []),
      volumeCell,
      oi24hChangeCell,
      oi7dChangeCell,
      oiUpdatedAtCell,
    ],
    symbolLink,
    priceLink,
    fundingRateCell,
    priceChangeCell,
    price7dChangeCell,
    oiValueCell,
    marketCapCell,
    volumeCell,
    oi24hChangeCell,
    oi7dChangeCell,
    oiUpdatedAtCell,
  };
}
```

- [ ] **Step 2: Render the market-cap cell when present**

In the same file, find:

```javascript
  cells.oiValueCell.textContent = formatCurrency(row.currentOiValue);
  cells.volumeCell.textContent = formatCurrency(row.volume24h);
```

Replace with:

```javascript
  cells.oiValueCell.textContent = formatCurrency(row.currentOiValue);
  if (cells.marketCapCell) {
    cells.marketCapCell.textContent = formatCurrency(row.marketCap);
  }
  cells.volumeCell.textContent = formatCurrency(row.volume24h);
```

- [ ] **Step 3: Opt in from the main ranking table**

In `realtime_oi_dashboard/static/js/components/OiRankingRow.js`, find:

```javascript
  const marketCells = createMarketRowCells();
```

Replace with:

```javascript
  const marketCells = createMarketRowCells({ includeMarketCap: true });
```

- [ ] **Step 4: Confirm the signal table is untouched**

Run: `grep -n "createMarketRowCells" realtime_oi_dashboard/static/js/components/HighOi7dTable.js`
Expected: one match, `tr._marketCells = createMarketRowCells();` — no args, so `includeMarketCap` defaults to `false` and that table's cell count is unchanged. Do not edit this file.

- [ ] **Step 5: Run the JS syntax checker**

Run: `node realtime_oi_dashboard/scripts/check-static-js.mjs`
Expected: exits 0

- [ ] **Step 6: Commit**

```bash
git add realtime_oi_dashboard/static/js/components/MarketRowCells.js realtime_oi_dashboard/static/js/components/OiRankingRow.js
git commit -m "Add optional market-cap cell to the main ranking table's rows"
```

---

### Task 7: Header cell and sort-dropdown option

**Files:**
- Modify: `realtime_oi_dashboard/index.html`

**Interfaces:**
- Consumes: `data-sort="marketCap"` is picked up automatically by the existing `document.querySelectorAll("th[data-sort]")` wiring in `dashboard.js` (no JS changes needed here) and by `VALID_SORT_KEYS` from Task 5.

- [ ] **Step 1: Add the table header cell**

In `realtime_oi_dashboard/index.html`, find:

```html
              <th scope="col" data-sort="currentOiValue"><span class="sort-label">持仓价值<span class="sort-arrows"></span></span></th>
              <th scope="col" data-sort="volume24h"><span class="sort-label">成交额(24h)<span class="sort-arrows"></span></span></th>
```

Replace with:

```html
              <th scope="col" data-sort="currentOiValue"><span class="sort-label">持仓价值<span class="sort-arrows"></span></span></th>
              <th scope="col" data-sort="marketCap"><span class="sort-label">市值<span class="sort-arrows"></span></span></th>
              <th scope="col" data-sort="volume24h"><span class="sort-label">成交额(24h)<span class="sort-arrows"></span></span></th>
```

- [ ] **Step 2: Add the sort-dropdown option**

Find:

```html
            <option value="currentOiValue">排序：持仓价值 高 → 低</option>
            <option value="volume24h">排序：成交额(24h) 高 → 低</option>
```

Replace with:

```html
            <option value="currentOiValue">排序：持仓价值 高 → 低</option>
            <option value="marketCap">排序：市值 高 → 低</option>
            <option value="volume24h">排序：成交额(24h) 高 → 低</option>
```

- [ ] **Step 3: Run the JS syntax checker**

Run: `node realtime_oi_dashboard/scripts/check-static-js.mjs`
Expected: exits 0 (this script also validates page IDs referenced from JS against `index.html`)

- [ ] **Step 4: Commit**

```bash
git add realtime_oi_dashboard/index.html
git commit -m "Add market cap header and sort option to the ranking table"
```

---

### Task 8: Column widths in `dashboard.css`

**Files:**
- Modify: `realtime_oi_dashboard/static/css/dashboard.css`

**Interfaces:**
- Consumes: nothing from other tasks — this is a pure CSS positional fix, needed because `.oi-table` column widths are pinned by `:nth-child(N)`, and Task 7 inserted a new column at position 8, shifting every column after it.

- [ ] **Step 1: Renumber the `.oi-table` column-width rules**

Find:

```css
.oi-table th:nth-child(1),
.oi-table td:nth-child(1) { width: 46px; }
.oi-table th:nth-child(2),
.oi-table td:nth-child(2) { width: 160px; }
.oi-table th:nth-child(3),
.oi-table td:nth-child(3) { width: 130px; }
.oi-table th:nth-child(4),
.oi-table td:nth-child(4) { width: 120px; }
.oi-table th:nth-child(5),
.oi-table td:nth-child(5) { width: 135px; }
.oi-table th:nth-child(6),
.oi-table td:nth-child(6) { width: 130px; }
.oi-table th:nth-child(7),
.oi-table td:nth-child(7) { width: 145px; }
.oi-table th:nth-child(8),
.oi-table td:nth-child(8) { width: 125px; }
.oi-table th:nth-child(9),
.oi-table td:nth-child(9) { width: 130px; }
.oi-table th:nth-child(10),
.oi-table td:nth-child(10) { width: 135px; }
.oi-table th:nth-child(11),
.oi-table td:nth-child(11) { width: 110px; }
```

Replace with:

```css
.oi-table th:nth-child(1),
.oi-table td:nth-child(1) { width: 46px; }
.oi-table th:nth-child(2),
.oi-table td:nth-child(2) { width: 160px; }
.oi-table th:nth-child(3),
.oi-table td:nth-child(3) { width: 130px; }
.oi-table th:nth-child(4),
.oi-table td:nth-child(4) { width: 120px; }
.oi-table th:nth-child(5),
.oi-table td:nth-child(5) { width: 135px; }
.oi-table th:nth-child(6),
.oi-table td:nth-child(6) { width: 130px; }
.oi-table th:nth-child(7),
.oi-table td:nth-child(7) { width: 145px; }
.oi-table th:nth-child(8),
.oi-table td:nth-child(8) { width: 120px; }
.oi-table th:nth-child(9),
.oi-table td:nth-child(9) { width: 125px; }
.oi-table th:nth-child(10),
.oi-table td:nth-child(10) { width: 130px; }
.oi-table th:nth-child(11),
.oi-table td:nth-child(11) { width: 135px; }
.oi-table th:nth-child(12),
.oi-table td:nth-child(12) { width: 110px; }
```

(Column 8 is now the new "市值" cell at 120px; the old columns 8–11 — 成交额/持仓24h/持仓7d/OI更新状态 — shift to 9–12 with their original widths preserved.)

- [ ] **Step 2: Confirm `.signal-table` rules are untouched**

Run: `grep -n "signal-table th:nth-child" realtime_oi_dashboard/static/css/dashboard.css`
Expected: still exactly 10 rule pairs (`nth-child(1)` through `nth-child(10)`), unchanged — the signal table has no market-cap column.

- [ ] **Step 3: Commit**

```bash
git add realtime_oi_dashboard/static/css/dashboard.css
git commit -m "Renumber oi-table column widths for the new market-cap column"
```

---

### Task 9: End-to-end manual verification and deploy

**Files:** none (verification only)

**Interfaces:** none — this task exercises everything built in Tasks 1–8 together.

- [ ] **Step 1: Run the full Python test suite**

Run: `python -m unittest discover -s tests -v`
Expected: all tests from Task 1 PASS, no other failures

- [ ] **Step 2: Run the JS syntax checker one more time**

Run: `node realtime_oi_dashboard/scripts/check-static-js.mjs`
Expected: exits 0

- [ ] **Step 3: Start the dashboard locally and confirm the column renders**

Run: `python main.py`
Then open `http://127.0.0.1:8777` in a browser and confirm:
- The main ranking table ("OI 变化排行") has a "市值" column between "持仓价值" and "成交额(24h)".
- BTC/ETH rows show a formatted market cap value (not `-`).
- At least one obscure/newly-listed symbol shows `-` (expected — no CoinGecko match).
- Clicking the "市值" column header sorts the table; the `#sortSelect` dropdown's "排序：市值 高 → 低" option does the same.
- The "7D OI 异动信号" table (top of the page) has NOT gained a market-cap column.

Stop the server with Ctrl+C when done.

- [ ] **Step 4: Deploy to Railway and verify the live site**

Run: `railway up --detach --service crypto-exchange-ticket --message "Add market cap column"`

Then poll `railway status --json` until the new deployment's instance status is `RUNNING`, and confirm via `railway logs --deployment --latest --lines 30` that there are no repeated errors (a handful of `marketCap` fetch errors right at cold start, before the first successful CoinGecko fetch, are expected and fine — they should stop appearing within `--market-cap-cache-seconds`, i.e. 15 minutes, once the first successful fetch lands).

Finally, `curl`/`Invoke-WebRequest` `https://crypto-exchange-ticket-production.up.railway.app/api/oi` and confirm the JSON has `"schema_version": 6` and at least one row with a non-null `"marketCap"`.

- [ ] **Step 5: Final commit (if anything was adjusted during manual testing)**

```bash
git add -A
git commit -m "Address manual verification findings for market cap column"
```

(Skip this step entirely if nothing needed adjusting.)
