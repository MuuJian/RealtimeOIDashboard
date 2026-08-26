import test from "node:test";
import assert from "node:assert/strict";

import { isOiPayload } from "../realtime_oi_dashboard/static/js/features/oi/OiPayloadSchema.js";

function payloadWithSymbol(symbol) {
  return {
    schema_version: 7,
    active_symbols: [symbol],
    total_symbols: 1,
    market_cap_loaded_symbols: 0,
    oi_dominance_history: [],
    rows: [],
    saved_at: null,
    error: null,
    recent_errors: [],
    cvd_meta: {
      serviceHealth: "unavailable",
      universeSymbols: 0,
      desiredShards: 0,
      activeShards: 0,
      connectedShards: 0,
      incomingMessagesPerSecond: 0,
      processingLagMs: 0,
      backfillQueueSize: 0,
      healthCounts: {
        warming: 0,
        live: 0,
        stale: 0,
        partial: 0,
        unavailable: 0,
      },
    },
  };
}

test("accepts the CVD service warming state", () => {
  const payload = {
    schema_version: 7,
    active_symbols: [],
    total_symbols: 0,
    market_cap_loaded_symbols: 0,
    oi_dominance_history: [],
    rows: [],
    saved_at: null,
    error: null,
    recent_errors: [],
    cvd_meta: {
      serviceHealth: "warming",
      universeSymbols: 500,
      desiredShards: 4,
      activeShards: 4,
      connectedShards: 4,
      incomingMessagesPerSecond: 100,
      processingLagMs: 5,
      backfillQueueSize: 0,
      healthCounts: {
        warming: 499,
        live: 1,
        stale: 0,
        partial: 0,
        unavailable: 0,
      },
    },
  };

  assert.equal(isOiPayload(payload), true);
});

test("OI dominance history contains BTC, ETH and OTHER shares", () => {
  const payload = payloadWithSymbol("BTCUSDT");
  payload.oi_dominance_history = [{
    timestamp: 1,
    btc: 40,
    eth: 30,
    other: 30,
    btcValue: 400,
    ethValue: 300,
    otherValue: 300,
  }];

  assert.equal(isOiPayload(payload), true);
  payload.oi_dominance_history[0].other = 31;
  assert.equal(isOiPayload(payload), false);
});

test("OI dominance shares match their notional values", () => {
  const payload = payloadWithSymbol("BTCUSDT");
  payload.oi_dominance_history = [{
    timestamp: 1,
    btc: 40,
    eth: 30,
    other: 30,
    btcValue: 800,
    ethValue: 300,
    otherValue: 300,
  }];

  assert.equal(isOiPayload(payload), false);
});

test("OI payload rejects duplicate symbols and rows outside the universe", () => {
  const payload = payloadWithSymbol("BTCUSDT");
  payload.active_symbols.push("BTCUSDT");
  payload.total_symbols = 2;
  assert.equal(isOiPayload(payload), false);

  const activePayload = payloadWithSymbol("BTCUSDT");
  activePayload.rows = [validRow("ETHUSDT")];
  assert.equal(isOiPayload(activePayload), false);

  const row = validRow("BTCUSDT");
  activePayload.rows = [row, { ...row }];
  assert.equal(isOiPayload(activePayload), false);
});

test("OI row validates derived values, explicit metrics, and funding time", () => {
  const payload = payloadWithSymbol("BTCUSDT");
  const row = validRow("BTCUSDT");
  payload.rows = [row];
  assert.equal(isOiPayload(payload), true);

  row.currentOiValue = 999;
  assert.equal(isOiPayload(payload), false);
  row.currentOiValue = 1_000;

  row.price7dChangePercent = 24;
  assert.equal(isOiPayload(payload), false);
  row.price7dChangePercent = 25;

  row.nextFundingTime = row.oiUpdatedAt;
  assert.equal(isOiPayload(payload), false);
  row.nextFundingTime = null;

  delete row.marketCap;
  assert.equal(isOiPayload(payload), false);
});

test("OI payload validates status metadata", () => {
  const valid = payloadWithSymbol("BTCUSDT");
  valid.saved_at = "2026-08-24T12:00:00+08:00";
  valid.error = "temporary";
  valid.recent_errors = [{ symbol: "exchangeInfo", error: "temporary" }];
  assert.equal(isOiPayload(valid), true);

  for (const mutate of [
    payload => { delete payload.saved_at; },
    payload => { payload.saved_at = "2026-02-30T12:00:00+08:00"; },
    payload => { payload.error = {}; },
    payload => { payload.recent_errors = "temporary"; },
  ]) {
    const payload = payloadWithSymbol("BTCUSDT");
    mutate(payload);
    assert.equal(isOiPayload(payload), false);
  }
});

function validRow(symbol) {
  return {
    symbol,
    price: 100,
    priceChangePercent: 1,
    price7dChangePercent: 25,
    fundingRatePercent: 0.01,
    currentOi: 10,
    currentOiValue: 1_000,
    oi24hChangePercent: 3,
    oi7dChangePercent: 4,
    marketCap: 10_000,
    volume24h: 2_000,
    oiUpdatedAt: 1_700_000_000_000,
    price7dBaseline: 80,
    nextFundingTime: 1_700_000_100_000,
  };
}
