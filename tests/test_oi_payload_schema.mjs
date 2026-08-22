import test from "node:test";
import assert from "node:assert/strict";

import { isOiPayload } from "../realtime_oi_dashboard/static/js/features/oi/OiPayloadSchema.js";

function payloadWithSymbol(symbol) {
  return {
    schema_version: 7,
    active_symbols: [symbol],
    total_symbols: 1,
    market_cap_loaded_symbols: 0,
    rows: [],
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
