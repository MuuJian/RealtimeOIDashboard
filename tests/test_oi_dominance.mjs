import test from "node:test";
import assert from "node:assert/strict";

import { buildOiDominance } from "../realtime_oi_dashboard/static/js/utils/oiDominance.js";

test("groups current OI value into BTC, ETH, SOL and OTHER", () => {
  const result = buildOiDominance([
    { symbol: "BTCUSDT", currentOiValue: 100 },
    { symbol: "ETHUSDT", currentOiValue: 50 },
    { symbol: "SOLUSDT", currentOiValue: 25 },
    { symbol: "XRPUSDT", currentOiValue: 15 },
    { symbol: "BNBUSDT", currentOiValue: 10 },
  ]);

  assert.equal(result.total, 200);
  assert.deepEqual(
    result.groups.map(({ key, value, percent }) => ({ key, value, percent })),
    [
      { key: "btc", value: 100, percent: 50 },
      { key: "eth", value: 50, percent: 25 },
      { key: "sol", value: 25, percent: 12.5 },
      { key: "other", value: 25, percent: 12.5 },
    ],
  );
});

test("ignores invalid and non-positive OI values", () => {
  const result = buildOiDominance([
    { symbol: "BTCUSDT", currentOiValue: null },
    { symbol: "ETHUSDT", currentOiValue: Number.NaN },
    { symbol: "SOLUSDT", currentOiValue: -1 },
    { symbol: "XRPUSDT", currentOiValue: 0 },
  ]);

  assert.equal(result.total, 0);
  assert.deepEqual(result.groups.map(group => group.percent), [0, 0, 0, 0]);
});
