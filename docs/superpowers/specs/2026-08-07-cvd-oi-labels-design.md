# CVD OI interpretation labels

## Goal

Add live 15-minute Cumulative Volume Delta (CVD) context to the OI ranking
table. It is informational only: existing OI values, rankings, filters, and
signals retain their current behaviour.

## Scope

- Track the 30 highest-24-hour-quote-volume USDT perpetual contracts.
- Use Binance Futures aggregated-trade WebSocket events as the source of
  taker-side flow.
- Show the 15-minute signed notional CVD, its normalized ratio, freshness, and
  an explanatory label for tracked OI rows.
- Do not persist CVD across process restarts in this first release.

## Architecture

`CvdPoller` is a third, optional background service alongside `OIPoller` and
`SignalScanPoller`. It refreshes its tracked symbol universe every minute and
maintains a combined `aggTrade` WebSocket subscription for those 30 symbols.

A pure domain rolling-window store receives normalized trade events. Each
event is stored as `(event_timestamp, signed_notional, absolute_notional)` and
expired events are removed outside the 15-minute window. The store returns a
per-symbol snapshot containing the signed CVD, the ratio
`signed_notional / absolute_notional`, the last-event timestamp, and coverage
age.

The OI API presenter reads a non-blocking snapshot of that service and merges
the CVD fields into matching OI rows. Missing, stale, or disconnected CVD data
does not fail `/api/oi` and never hides OI data.

## Trade direction

Binance `aggTrade.m` means the buyer is the maker. Therefore:

- `m == false`: a taker bought; add `price * quantity`.
- `m == true`: a taker sold; subtract `price * quantity`.

All CVD values are USDT notionals, avoiding misleading comparisons between
assets with very different unit prices.

## Public row contract

Each OI row gains optional fields:

- `cvd15m`: signed CVD notional in USDT.
- `cvd15mRatio`: signed CVD divided by total taker notional, as a decimal.
- `cvdStatus`: one of `buying`, `selling`, `neutral`, `collecting`,
  `untracked`, or `unavailable`.
- `cvdUpdatedAt`: Unix milliseconds for the latest accepted trade.

Rows are `untracked` when their symbol is outside the 30-symbol CVD universe,
`collecting` until 15 minutes of coverage are available, and `unavailable`
when the CVD service has no fresh connection state. A complete window with a
ratio of at least +10% is `buying`; at most -10% is `selling`; otherwise it is
`neutral`.

## UI

The OI table adds `CVD (15m)` and `判讀` columns. The former formats a signed
USDT value and signed percentage; the latter renders a label:

- `買盤主導` for `buying`.
- `賣盤主導` for `selling`.
- `中性` for `neutral`.
- `資料累積中`, `未追蹤`, or `資料不可用` for the remaining states.

These columns are not sortable or filterable in the initial release. Tooltips
explain that CVD measures taker flow, not a guaranteed price direction.

## Failure handling

The WebSocket client reconnects with bounded exponential backoff and responds
to cancellation promptly. A connection failure marks CVD unavailable but does
not stop the HTTP server, OI service, or signal scan. Malformed trade events
are ignored and recorded without ending the stream. The CVD service is
optional at bootstrap, following the existing signal-scan failure behaviour.

## Tests

- Domain tests for maker direction, signed notional, pruning, normalization,
  status thresholds, and incomplete coverage.
- Service tests for universe changes, malformed events, cancellation, stale
  snapshots, and reconnect failure isolation.
- Presenter/API tests that ensure CVD merges only with matching rows and does
  not alter unavailable OI responses.
- Front-end schema and rendering tests for all CVD states.
