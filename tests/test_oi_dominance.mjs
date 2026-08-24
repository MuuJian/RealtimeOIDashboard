import test from "node:test";
import assert from "node:assert/strict";

import { buildOiDominance } from "../realtime_oi_dashboard/static/js/utils/oiDominance.js";
import {
  dominanceAriaLabel,
  dominancePointIndexAtRatio,
  dominancePointPositions,
} from "../realtime_oi_dashboard/static/js/utils/oiDominanceChart.js";

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
  assert.equal(
    dominanceAriaLabel(result),
    "OI 市場佔比當前：BTC 50.0%，ETH 25.0%，OTHER 25.0%",
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

test("does not publish current dominance when finite rows overflow in aggregate", () => {
  const result = buildOiDominance([
    currentRow("BTCUSDT", 1e308),
    currentRow("ETHUSDT", 1e308),
    currentRow("SOLUSDT", 1e308),
    currentRow("XRPUSDT", 1e308),
  ], [], 4);

  assert.equal(result.total, 0);
  assert.deepEqual(result.groups.map(group => group.value), [0, 0, 0]);
  assert.deepEqual(result.groups.map(group => group.percent), [0, 0, 0]);
  assert.equal(dominanceAriaLabel(result), "OI 市場佔比暫無資料");
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

test("anchors the current chart point to the latest exchange OI timestamp", () => {
  const result = buildOiDominance([
    { ...currentRow("BTCUSDT", 100), oiUpdatedAt: 1_700_000_000_000 },
    { ...currentRow("ETHUSDT", 100), oiUpdatedAt: 1_700_000_100_000 },
    { ...currentRow("SOLUSDT", 100), oiUpdatedAt: "invalid" },
  ]);

  assert.equal(result.timestamp, 1_700_000_100_000);
  assert.equal(result.points.at(-1).timestamp, 1_700_000_100_000);
});

test("does not append an empty current point to valid history", () => {
  const history = [
    historyPoint(100, 40),
    historyPoint(200, 45),
  ];

  const result = buildOiDominance([], history);

  assert.equal(result.total, 0);
  assert.deepEqual(
    result.points.map(point => point.timestamp),
    [100, 200],
  );
  assert.equal(result.points.at(-1).groups[0].percent, 45);
  assert.equal(
    dominanceAriaLabel(result),
    "OI 市場佔比最近歷史：BTC 45.0%，ETH 30.0%，OTHER 25.0%",
  );
});

test("keeps chart history strictly earlier than the current snapshot", () => {
  const rows = [
    { ...currentRow("BTCUSDT", 100), oiUpdatedAt: 200 },
    { ...currentRow("ETHUSDT", 100), oiUpdatedAt: 200 },
  ];
  const result = buildOiDominance(rows, [
    historyPoint(100, 40),
    historyPoint(200, 45),
    historyPoint(300, 50),
  ]);

  assert.deepEqual(
    result.points.map(point => point.timestamp),
    [100, 200],
  );
});

test("positions dominance points by elapsed time", () => {
  const points = [
    { timestamp: 100 },
    { timestamp: 110 },
    { timestamp: 200 },
  ];

  assert.deepEqual(dominancePointPositions(points), [0, 0.1, 1]);
  assert.equal(dominancePointIndexAtRatio(points, 0.7), 2);
});

test("does not publish current dominance from a partial symbol universe", () => {
  const result = buildOiDominance([
    currentRow("BTCUSDT", 100),
    currentRow("ETHUSDT", 100),
  ], [], 3);

  assert.equal(result.total, 0);
  assert.equal(dominanceAriaLabel(result), "OI 市場佔比暫無資料");
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

function historyPoint(timestamp, btc) {
  return {
    timestamp,
    btc,
    eth: 30,
    other: 70 - btc,
    btcValue: btc,
    ethValue: 30,
    otherValue: 70 - btc,
  };
}
