import test from "node:test";
import assert from "node:assert/strict";

import { buildOiDominance } from "../realtime_oi_dashboard/static/js/utils/oiDominance.js";

test("groups current OI value into BTC, ETH and OTHER", () => {
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
      { key: "other", value: 50, percent: 25 },
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
  assert.deepEqual(result.groups.map(group => group.percent), [0, 0, 0]);
});

test("uses the complete historical series for the chart", () => {
  const history = Array.from({ length: 12 }, (_, index) => ({
    timestamp: index + 1,
    btc: 30 + index,
    eth: 30,
    other: 40 - index,
    btcValue: 300 + index,
    ethValue: 300,
    otherValue: 400 - index,
  }));
  const result = buildOiDominance([
    currentRow("BTCUSDT", 100),
    currentRow("ETHUSDT", 100),
  ], history);

  assert.equal(result.points.length, 13);
  assert.equal(result.points[0].groups[0].percent, 30);
  assert.equal(result.points[11].groups[0].percent, 41);
  assert.equal(result.points[12].groups[0].percent, 50);
  assert.equal(result.points[0].groups[0].value, 300);
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
