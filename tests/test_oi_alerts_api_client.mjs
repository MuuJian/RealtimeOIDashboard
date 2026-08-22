import test from "node:test";
import assert from "node:assert/strict";

import {
  loadOiAlerts,
  saveOiAlertsConfig,
  sendOiAlertsTestMessage,
} from "../realtime_oi_dashboard/static/js/features/oi-alerts/OiAlertsApiClient.js";

const validPayload = {
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
    symbols: [],
  },
  telegram: { status: "not_configured", last_error: null, last_attempt_at: null },
  storage: { status: "ok", last_error: null },
  active: [],
  events: [],
};

function installWindow() {
  const previousWindow = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout };
  return () => {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  };
}

test("loads OI alerts with a no-cache GET request", async () => {
  const restoreWindow = installWindow();
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => validPayload };
  };

  try {
    assert.deepEqual(await loadOiAlerts(), validPayload);
    assert.equal(requests.length, 1);
    assert.equal(requests[0].url, "/api/oi-alerts");
    assert.equal(requests[0].options.method, "GET");
    assert.equal(requests[0].options.cache, "no-cache");
  } finally {
    restoreWindow();
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("saves thresholds in USD without sending credentials", async () => {
  const restoreWindow = installWindow();
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => validPayload };
  };

  try {
    await saveOiAlertsConfig({
      enabled: true,
      thresholds: [75e6, 100e6, 150e6],
    });
    assert.equal(requests[0].url, "/api/oi-alerts/config");
    assert.equal(requests[0].options.method, "PUT");
    assert.equal(requests[0].options.headers["Content-Type"], "application/json");
    assert.deepEqual(JSON.parse(requests[0].options.body), {
      enabled: true,
      thresholds: [75e6, 100e6, 150e6],
    });
    assert.equal(requests[0].options.body.includes("token"), false);
    assert.equal(requests[0].options.body.includes("chat_id"), false);
  } finally {
    restoreWindow();
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("uses the server validation message for failed alert requests", async () => {
  const restoreWindow = installWindow();
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 400,
    json: async () => ({ error: "Invalid alert configuration" }),
  });

  try {
    await assert.rejects(
      saveOiAlertsConfig({ enabled: true, thresholds: [100e6, 75e6, 150e6] }),
      error => error.message === "Invalid alert configuration",
    );
  } finally {
    restoreWindow();
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("posts an empty test-message request without credentials", async () => {
  const restoreWindow = installWindow();
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      json: async () => ({
        queued: false,
        telegram: validPayload.telegram,
      }),
    };
  };

  try {
    const result = await sendOiAlertsTestMessage();
    assert.equal(result.queued, false);
    assert.equal(requests[0].url, "/api/oi-alerts/test-message");
    assert.equal(requests[0].options.method, "POST");
    assert.equal(requests[0].options.body, "{}");
  } finally {
    restoreWindow();
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});
