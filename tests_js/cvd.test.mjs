import assert from "node:assert/strict";
import test from "node:test";

import {
  cvdStatusLabel,
  formatCvd,
  formatCvdAmount,
  formatCvdRatio,
} from "../realtime_oi_dashboard/static/js/utils/cvd.js";
import { buildVisibleRows } from "../realtime_oi_dashboard/static/js/utils/rankingRows.js";

test("formats signed CVD notional and ratio", () => {
  assert.equal(formatCvd(1_250_000, 0.18), "+$1.25M · +18.0%");
  assert.equal(formatCvd(-25_000, -0.1), "-$25.00K · -10.0%");
  assert.equal(formatCvdAmount(1_250_000), "+$1.25M");
  assert.equal(formatCvdRatio(-0.1), "-10.0%");
  assert.equal(formatCvdAmount(null), "-");
  assert.equal(formatCvdRatio(null), "-");
});

test("returns readable status labels", () => {
  assert.equal(cvdStatusLabel("buying"), "買盤主導");
  assert.equal(cvdStatusLabel("collecting"), "資料累積中");
  assert.equal(cvdStatusLabel("unavailable"), "資料不可用");
  assert.equal(cvdStatusLabel("buying", "stale"), "資料延遲");
  assert.equal(cvdStatusLabel("selling", "partial"), "資料不完整");
});

test("sorts CVD by ratio instead of notional", () => {
  const rows = [
    { symbol: "LARGEUSDT", cvd15m: 5_000_000, cvd15mRatio: 0.05 },
    { symbol: "STRONGUSDT", cvd15m: 10_000, cvd15mRatio: 0.4 },
    { symbol: "SELLUSDT", cvd15m: -20_000, cvd15mRatio: -0.2 },
  ];
  const filters = {
    query: "",
    favoritesOnly: false,
    minOiValue: 0,
    minVolume: 0,
    limit: 99999,
  };

  const sorted = buildVisibleRows(
    rows,
    filters,
    { sortKey: "cvd15mRatio", sortDir: "desc" },
    new Set(),
  );

  assert.deepEqual(sorted.map(row => row.symbol), [
    "STRONGUSDT",
    "LARGEUSDT",
    "SELLUSDT",
  ]);
});
