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
