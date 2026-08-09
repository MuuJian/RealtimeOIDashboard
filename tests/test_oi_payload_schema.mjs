import test from "node:test";
import assert from "node:assert/strict";

import { isOiPayload } from "../realtime_oi_dashboard/static/js/features/oi/OiPayloadSchema.js";

test("accepts the CVD service warming state", () => {
  const payload = {
    schema_version: 7,
    active_symbols: [],
    total_symbols: 0,
    market_cap_loaded_symbols: 0,
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
