import test from "node:test";
import assert from "node:assert/strict";

import { isOiAlertsPayload } from "../realtime_oi_dashboard/static/js/features/oi-alerts/OiAlertsPayloadSchema.js";

function payload(overrides = {}) {
  return {
    schema_version: 2,
    config: {
      enabled: true,
      thresholds: [75e6, 100e6, 150e6],
      scale_alerts_enabled: true,
      change_window_minutes: 15,
      min_oi_change_percent: 3,
      min_price_change_percent: 0.5,
      require_cvd_confirmation: false,
      cooldown_minutes: 30,
      symbols: ["BTCUSDT"],
    },
    telegram: { status: "configured", last_error: null, last_attempt_at: null },
    storage: { status: "ok", last_error: null },
    active: [],
    events: [],
    ...overrides,
  };
}

test("accepts the unified OI alert rule payload", () => {
  assert.equal(isOiAlertsPayload(payload()), true);
});

test("accepts Unicode Binance symbols in rules, active alerts, and event history", () => {
  const active = {
    symbol: "币安人生USDT",
    event_type: "oi_scale",
    oi_value: 100e6,
    threshold: 75e6,
    signal: "OI scale alert",
    oi_change_percent: null,
    price_change_percent: null,
    explanation: "test",
    as_of: "2026-08-22T00:00:00Z",
  };
  const event = {
    ...active,
    event_id: "unicode-event",
    triggered_at: active.as_of,
    exchange_timestamp_ms: 1_787_356_800_000,
    delivery_status: "sent",
    failure_reason: null,
    last_attempt_at: active.as_of,
  };
  assert.equal(isOiAlertsPayload(payload({
    config: { ...payload().config, symbols: [active.symbol] },
    active: [active],
    events: [event],
  })), true);
  for (const symbol of ["币安人生USDT ", "币安/人生USDT", "btCUSDT", "USDT"]) {
    assert.equal(isOiAlertsPayload(payload({ active: [{ ...active, symbol }] })), false);
  }
});

test("rejects malformed symbols and non-finite signal metrics", () => {
  assert.equal(isOiAlertsPayload(payload({
    config: { ...payload().config, symbols: ["btc"] },
  })), false);
  assert.equal(isOiAlertsPayload(payload({
    active: [{
      symbol: "BTCUSDT",
      event_type: "oi_expansion",
      oi_value: 100e6,
      threshold: 3,
      signal: "Bullish OI expansion",
      oi_change_percent: Number.NaN,
      price_change_percent: 1,
      explanation: "test",
      as_of: "2026-08-22T00:00:00Z",
    }],
  })), false);
});
