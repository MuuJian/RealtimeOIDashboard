import test from "node:test";
import assert from "node:assert/strict";

import { createOiAlertsRefreshController } from "../realtime_oi_dashboard/static/js/features/oi-alerts/OiAlertsRefreshController.js";

const validPayload = {
  config: { enabled: true, thresholds: [75e6, 100e6, 150e6] },
  telegram: { status: "not_configured", last_error: null, last_attempt_at: null },
  active: [],
  events: [],
};

function tick() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

test("stopping an alert refresh aborts its active request", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const intervals = new Set();
  let requestSignal;
  globalThis.window = {
    setTimeout,
    clearTimeout,
    setInterval(callback) {
      intervals.add(callback);
      return callback;
    },
    clearInterval(callback) {
      intervals.delete(callback);
    },
  };
  globalThis.fetch = async (_url, { signal }) => {
    requestSignal = signal;
    return new Promise(() => {});
  };
  const controller = createOiAlertsRefreshController({
    onPayload: () => {},
    onError: () => {},
  });

  try {
    controller.start();
    await tick();
    assert.equal(controller.isRunning(), true);
    assert.equal(requestSignal.aborted, false);

    controller.stop();
    assert.equal(requestSignal.aborted, true);
    assert.equal(controller.isRunning(), false);
  } finally {
    controller.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("ignores a response from a stopped alert refresh generation", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  let releaseResponse;
  const responseReleased = new Promise(resolve => {
    releaseResponse = resolve;
  });
  globalThis.window = {
    setTimeout,
    clearTimeout,
    setInterval: () => 1,
    clearInterval: () => {},
  };
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => {
      await responseReleased;
      return validPayload;
    },
  });
  const payloads = [];
  const controller = createOiAlertsRefreshController({
    onPayload: payload => payloads.push(payload),
    onError: () => {},
  });

  try {
    controller.start();
    await tick();
    controller.stop();
    releaseResponse();
    await tick();
    assert.deepEqual(payloads, []);
  } finally {
    controller.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});
