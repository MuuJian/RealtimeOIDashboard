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
  };
}

test("OI payload symbols require uppercase ASCII letters and digits", () => {
  for (const symbol of ["BTCUSDT", "1000PEPEUSDT", "BTCDOMUSDT"]) {
    assert.equal(isOiPayload(payloadWithSymbol(symbol)), true, symbol);
  }

  for (const symbol of [
    "",
    "btcusdt",
    "BtcUSDT",
    "BTC-USDT",
    "BTC_USDT",
    " BTCUSDT",
    "BTCUSDT ",
    "ＢＴＣUSDT",
    "坏USDT",
  ]) {
    assert.equal(isOiPayload(payloadWithSymbol(symbol)), false, symbol);
  }
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
    btcValue: 400,
    ethValue: 300,
    otherValue: 300,
  }];

  payload.oi_dominance_history[0].btcValue = 800;
  assert.equal(isOiPayload(payload), false);

  payload.oi_dominance_history[0] = {
    timestamp: 1,
    btc: 33.33,
    eth: 33.33,
    other: 33.34,
    btcValue: 1,
    ethValue: 1,
    otherValue: 1,
  };
  assert.equal(isOiPayload(payload), true);

  payload.oi_dominance_history[0].btcValue = 0;
  payload.oi_dominance_history[0].ethValue = 0;
  payload.oi_dominance_history[0].otherValue = 0;
  assert.equal(isOiPayload(payload), false);
});

test("OI payload rejects duplicate active symbols", () => {
  const payload = payloadWithSymbol("BTCUSDT");
  payload.active_symbols.push("BTCUSDT");
  payload.total_symbols = 2;

  assert.equal(isOiPayload(payload), false);
});

test("OI payload rows are unique active symbols", () => {
  const payload = payloadWithSymbol("BTCUSDT");
  const row = validRow("BTCUSDT");

  payload.rows = [row];
  assert.equal(isOiPayload(payload), true);

  payload.rows = [row, { ...row }];
  assert.equal(isOiPayload(payload), false);

  payload.rows = [validRow("ETHUSDT")];
  assert.equal(isOiPayload(payload), false);
});

test("OI payload validates dashboard status metadata", () => {
  const valid = payloadWithSymbol("BTCUSDT");
  valid.saved_at = "2026-08-24T12:00:00+08:00";
  valid.error = "temporary";
  valid.recent_errors = [{
    symbol: "exchangeInfo",
    error: "temporary",
  }];
  assert.equal(isOiPayload(valid), true);

  for (const mutate of [
    payload => { delete payload.saved_at; },
    payload => { payload.saved_at = "not-a-timestamp"; },
    payload => { payload.saved_at = "2026-02-30T12:00:00+08:00"; },
    payload => { payload.error = {}; },
    payload => { payload.recent_errors = "temporary"; },
    payload => { payload.recent_errors = [{ symbol: "BTCUSDT", error: 1 }]; },
    payload => {
      payload.recent_errors = Array.from(
        { length: 11 },
        () => ({ symbol: "BTCUSDT", error: "temporary" }),
      );
    },
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
    price7dChangePercent: 2,
    fundingRatePercent: 0.01,
    currentOi: 10,
    currentOiValue: 1_000,
    oi24hChangePercent: 3,
    oi7dChangePercent: 4,
    marketCap: 10_000,
    volume24h: 2_000,
    oiUpdatedAt: 1_700_000_000_000,
    price7dBaseline: 90,
    nextFundingTime: 1_700_000_100_000,
  };
}
