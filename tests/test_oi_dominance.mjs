import test from "node:test";
import assert from "node:assert/strict";

import { buildOiDominance } from "../realtime_oi_dashboard/static/js/utils/oiDominance.js";

test("groups current OI value into BTC, ETH, SOL and OTHER", () => {
  const result = buildOiDominance([
    currentRow("BTCUSDT", 100),
    currentRow("ETHUSDT", 50),
    currentRow("SOLUSDT", 25),
    currentRow("XRPUSDT", 15),
    currentRow("BNBUSDT", 10),
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
    { symbol: "BTCUSDT", currentOi: null, price: 1 },
    { symbol: "ETHUSDT", currentOi: Number.NaN, price: 1 },
    { symbol: "SOLUSDT", currentOi: -1, price: 1 },
    { symbol: "XRPUSDT", currentOi: 0, price: 1 },
  ]);

  assert.equal(result.total, 0);
  assert.deepEqual(result.groups.map(group => group.percent), [0, 0, 0, 0]);
});

test("builds real 7d and 24h dominance points from row baselines", () => {
  const result = buildOiDominance([
    {
      ...currentRow("BTCUSDT", 100),
      oi24hChangePercent: 100,
      priceChangePercent: 0,
      oi7dChangePercent: 300,
      price7dBaseline: 1,
    },
    currentRow("ETHUSDT", 100),
  ]);

  assert.deepEqual(
    result.points.map(point => point.groups[0].percent),
    [20, 1 / 3 * 100, 50],
  );
});

function currentRow(symbol, currentOiValue) {
  return {
    symbol,
    currentOi: currentOiValue,
    price: 1,
    currentOiValue,
    oi24hChangePercent: 0,
    priceChangePercent: 0,
    oi7dChangePercent: 0,
    price7dBaseline: 1,
  };
}
