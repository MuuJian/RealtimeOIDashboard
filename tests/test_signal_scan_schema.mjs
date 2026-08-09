import test from "node:test";
import assert from "node:assert/strict";

import { isSignalScanPayload } from "../realtime_oi_dashboard/static/js/features/signal-scan/SignalScanPayloadSchema.js";

function signalRow(overrides = {}) {
  return {
    symbol: "BTCUSDT",
    price: 100,
    chg1h: 1,
    chg24h: 2,
    aboveE20: 3,
    volRatio: 1,
    isBull: false,
    isBear: false,
    ...overrides,
  };
}

function payload(overrides = {}) {
  return {
    schema_version: 2,
    bulls: [],
    bears: [],
    spikes: [],
    saved_at: "2026-08-07T16:00:00+08:00",
    error: null,
    scan_total: 1,
    scan_succeeded: 1,
    partial: false,
    recent_errors: [],
    ...overrides,
  };
}

test("rejects a signal row that is both bullish and bearish", () => {
  assert.equal(
    isSignalScanPayload(
      payload({
        bulls: [signalRow({ isBull: true, isBear: true })],
      }),
    ),
    false,
  );
});

test("accepts a symbol that appears in trend and volatility result tables", () => {
  assert.equal(
    isSignalScanPayload(
      payload({
        bulls: [signalRow({ isBull: true })],
        spikes: [signalRow({ isBull: true })],
      }),
    ),
    true,
  );
});

test("rejects an error payload that still contains signal rows", () => {
  assert.equal(
    isSignalScanPayload(
      payload({
        bulls: [signalRow({ isBull: true })],
        error: "scan failed",
        partial: true,
        scan_total: 2,
        scan_succeeded: 1,
      }),
    ),
    false,
  );
});

test("accepts a signal row with at most one trend direction", () => {
  assert.equal(
    isSignalScanPayload(
      payload({
        bulls: [signalRow({ isBull: true })],
      }),
    ),
    true,
  );
  assert.equal(
    isSignalScanPayload(
      payload({
        bears: [signalRow({ isBear: true })],
      }),
    ),
    true,
  );
});

test("rejects payload arrays above the server result limits", () => {
  const rows = Array.from({ length: 9 }, (_, index) => (
    signalRow({ symbol: `S${index}USDT` })
  ));

  assert.equal(isSignalScanPayload(payload({ bulls: rows })), false);
  assert.equal(
    isSignalScanPayload(
      payload({
        spikes: Array.from({ length: 11 }, (_, index) => (
          signalRow({ symbol: `S${index}USDT` })
        )),
      }),
    ),
    false,
  );
  assert.equal(
    isSignalScanPayload(
      payload({
        recent_errors: Array.from({ length: 11 }, (_, index) => ({
          symbol: `S${index}USDT`,
          error: "failure",
        })),
      }),
    ),
    false,
  );
});

test("enforces the server recent-error text limit", () => {
  const baseError = {
    symbol: "BTCUSDT",
    error: "x".repeat(512),
  };

  assert.equal(
    isSignalScanPayload(payload({ recent_errors: [baseError] })),
    true,
  );
  assert.equal(
    isSignalScanPayload(
      payload({
        recent_errors: [{ ...baseError, error: `${baseError.error}x` }],
      }),
    ),
    false,
  );
});

test("counts recent-error text as Unicode code points", () => {
  const baseError = {
    symbol: "BTCUSDT",
    error: "😀".repeat(512),
  };

  assert.equal(
    isSignalScanPayload(payload({ recent_errors: [baseError] })),
    true,
  );
  assert.equal(
    isSignalScanPayload(
      payload({
        recent_errors: [{ ...baseError, error: `${baseError.error}😀` }],
      }),
    ),
    false,
  );
});

test("rejects timestamps with normalized but invalid calendar fields", () => {
  for (const savedAt of [
    "2026-02-31T16:00:00+08:00",
    "2026-04-31T16:00:00+08:00",
    "2026-01-01T24:00:00+08:00",
    "2026-01-01T16:00:00+24:00",
  ]) {
    assert.equal(isSignalScanPayload(payload({ saved_at: savedAt })), false);
  }
});
