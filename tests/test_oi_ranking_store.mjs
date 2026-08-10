import test from "node:test";
import assert from "node:assert/strict";

import { createOiRankingStore } from "../realtime_oi_dashboard/static/js/features/oi/OiRankingStore.js";

function row(symbol, priceChangePercent) {
  return {
    symbol,
    price: 100,
    volume24h: 1_000,
    currentOi: 10,
    currentOiValue: 1_000,
    marketCap: 10_000,
    oiUpdatedAt: 1,
    price7dBaseline: 90,
    nextFundingTime: null,
    priceChangePercent,
    price7dChangePercent: 10,
    fundingRatePercent: 0.01,
    oi24hChangePercent: 1,
    oi7dChangePercent: 2,
  };
}

test("recomputes top movers after live ticker updates", () => {
  const store = createOiRankingStore();
  store.setRows([
    row("AAAUSDT", 10),
    row("BBBUSDT", 5),
  ], new Map());
  assert.equal(store.getStats().topIncrease.symbol, "AAAUSDT");

  const affected = store.applyPriceUpdates(
    new Set(["BBBUSDT"]),
    new Map([["BBBUSDT", {
      price: 101,
      volume24h: 1_100,
      priceChangePercent: 20,
    }]]),
  );

  assert.deepEqual(affected, ["BBBUSDT"]);
  assert.equal(store.getStats().topIncrease.symbol, "BBBUSDT");
  assert.equal(store.getStats().topIncrease.priceChangePercent, 20);
});
