# Market Cap Column — Design

## Context

This deployment is a local fork of [MuuJian/RealtimeOIDashboard](https://github.com/MuuJian/RealtimeOIDashboard), running on Railway. The dashboard shows Binance USDⓈ-M perpetual futures: live price, open interest (OI), OI value (OI × price), funding rate, and 24h/7d changes. All of that comes directly from Binance's futures API.

The user wants a **market cap** column. Binance's futures API has no circulating-supply or market-cap data, so this requires a new external data source and a new server-side data path. This is a local customization on top of the upstream project — it will not be pushed upstream (no write access, and it's out of scope for the upstream author's project).

## Goals

- Add a "市值" (market cap) column to the main ranking table ("OI 变化排行"), sortable like the other numeric columns.
- Data refreshes periodically in the background; does not block or slow down the existing price/OI polling loop.
- Missing/unmatched symbols show `-` rather than breaking the row or the page.

## Non-goals

- Not adding market cap to the "7D OI 异动信号" table (kept compact, per user).
- Not building a manual Binance-symbol → CoinGecko-id mapping table. Matching is best-effort/automatic; mismatches or gaps are accepted.
- Not guaranteeing 100% symbol coverage — thinly-traded or newly-listed contracts may show `-` until they appear in CoinGecko's top-500-by-market-cap list.

## Architecture

### 1. New module: `realtime_oi_dashboard/market_cap_cache.py`

Mirrors the existing `market_cache.py` pattern (a `dataclass` cache with `cache_seconds` / staleness tracking), but holds a single flat `symbol_ticker -> market_cap` dict rather than per-request funding/ticker payloads.

Responsibilities:
- Fetch `GET https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=1` and `page=2` (500 coins total — covers effectively every coin with an active Binance perpetual).
- Build a `{TICKER: market_cap}` map from the response (`symbol` field uppercased), keeping the highest-market-cap entry when a ticker collides.
- On fetch failure: keep serving the last good snapshot (same "stale-but-served" behavior as `market_cache.py`); log the error; never raise into the polling loop.
- Refresh interval: configurable via new CLI flag `--market-cap-cache-seconds` (default `900`, i.e. 15 minutes — market cap doesn't need to be fresher than that).

### 2. Symbol matching (`poller.py` or a small helper in the new module)

For each Binance contract symbol:
1. Strip a numeric contract-multiplier prefix if present (`1000`, `1000000`, etc. — same style of normalization already used elsewhere for display).
2. Strip the `USDT` quote-asset suffix.
3. Look up the resulting ticker in the market-cap map (case-insensitive).
4. No match → `marketCap: None`, rendered as `-` on the frontend.

This is intentionally simple: no manual override table, no disambiguation logic for tickers shared by multiple coins across chains — first/highest-market-cap match wins, per user's explicit choice.

### 3. `poller.py` integration

In `build_symbol_update`, after computing the existing row fields, look up `marketCap` from the new cache (read-only, non-blocking — the cache refreshes on its own timer, not per-row) and add it to the `row` dict alongside `currentOiValue`, `fundingRatePercent`, etc.

### 4. `/api/oi` response

`marketCap` rides along in each row object automatically once it's in `row` — no separate endpoint needed.

### 5. Frontend

- `index.html`: add a `<th>市值</th>` header to the `oi-table` (main ranking table only), and a corresponding `<option value="marketCap">排序：市值 高 → 低</option>` in `#sortSelect`.
- `MarketRowCells.js`: render the new cell, formatted with the existing compact-number formatter (same style as OI value / volume — e.g. `1.2B`, `450M`); `-` when `marketCap` is `null`/missing.
- `useTableSort.js`: no changes needed beyond the existing generic numeric-sort path, since `marketCap` is just another numeric field on the row.

## Data flow summary

```
CoinGecko /coins/markets (2 pages, every 15 min)
        │
        ▼
market_cap_cache.py  (symbol ticker -> market_cap, stale-serving on failure)
        │
        ▼
poller.py: build_symbol_update()  →  row["marketCap"]
        │
        ▼
/api/oi  →  browser  →  oi-table "市值" column (sortable, compact-formatted)
```

## Error handling

- CoinGecko unreachable / non-200 / malformed JSON: log and keep the previous cached map; if there is no previous map yet (cold start), all rows show `-` until the first successful fetch.
- Ticker with no match: `marketCap: None` → `-`, not an error.
- This must never raise out of the polling loop — same defensive posture as the existing `market_cache.py` / funding-rate fetch path.

## Testing

- Unit-test the ticker-normalization function (prefix/suffix stripping) with a handful of real symbols (`1000PEPEUSDT`, `1000000BOBUSDT`, `BTCUSDT`, an unmatchable made-up symbol).
- Unit-test `market_cap_cache.py`'s stale-serving behavior on a simulated fetch failure, following the existing test patterns for `market_cache.py` if present.
- Manual check after deploying: confirm the "市值" column populates for major symbols (BTC, ETH) and shows `-` for at least one obscure/newly-listed symbol, and that sorting by it works.

## Deployment note

This is a local-only patch on top of the cloned upstream repo. Future `git pull --ff-only` from `MuuJian/RealtimeOIDashboard` will re-apply cleanly as long as upstream doesn't touch the same lines — if a future upstream update conflicts with this patch, it needs manual reconciliation at pull time (not a fast-forward).
