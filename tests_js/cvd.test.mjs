import assert from "node:assert/strict";
import test from "node:test";

import { cvdStatusLabel, formatCvd } from "../realtime_oi_dashboard/static/js/utils/cvd.js";

test("formats signed CVD notional and ratio", () => {
  assert.equal(formatCvd(1_250_000, 0.18), "+$1.25M · +18.0%");
  assert.equal(formatCvd(-25_000, -0.1), "-$25.00K · -10.0%");
});

test("returns readable status labels", () => {
  assert.equal(cvdStatusLabel("buying"), "買盤主導");
  assert.equal(cvdStatusLabel("collecting"), "資料累積中");
  assert.equal(cvdStatusLabel("unavailable"), "資料不可用");
  assert.equal(cvdStatusLabel("buying", "stale"), "資料延遲");
  assert.equal(cvdStatusLabel("selling", "partial"), "資料不完整");
});
