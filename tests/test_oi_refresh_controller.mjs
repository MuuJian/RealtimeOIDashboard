import test from "node:test";
import assert from "node:assert/strict";

import { createOiRefreshController } from "../realtime_oi_dashboard/static/js/features/oi/OiRefreshController.js";

const validPayload = {
  schema_version: 7,
  active_symbols: [],
  total_symbols: 0,
  market_cap_loaded_symbols: 0,
  oi_dominance_history: [],
  rows: [],
};

function tick() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

test("queues an immediate refresh behind an asynchronously cancelled request", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const activeIntervals = new Set();
  const fetchCalls = [];
  let releaseFirstResponse;
  const firstResponseReleased = new Promise(resolve => {
    releaseFirstResponse = resolve;
  });

  globalThis.window = {
    setTimeout,
    clearTimeout,
    setInterval(callback) {
      activeIntervals.add(callback);
      return callback;
    },
    clearInterval(callback) {
      activeIntervals.delete(callback);
    },
  };
  globalThis.fetch = async (_url, { signal }) => {
    fetchCalls.push(signal);
    if (fetchCalls.length === 1) {
      return {
        ok: true,
        json: async () => {
          await firstResponseReleased;
          return validPayload;
        },
      };
    }
    return {
      ok: true,
      json: async () => validPayload,
    };
  };

  const payloads = [];
  const errors = [];
  const controller = createOiRefreshController({
    onPayload: payload => payloads.push(payload),
    onError: error => errors.push(error),
    onSettled: () => {},
    refreshIntervalMs: 60_000,
  });

  try {
    controller.start();
    await tick();
    assert.equal(fetchCalls.length, 1);

    controller.stop();
    controller.start();
    await tick();
    assert.equal(fetchCalls.length, 1);
    assert.equal(fetchCalls[0].aborted, true);

    releaseFirstResponse();
    for (let attempt = 0; attempt < 10 && fetchCalls.length < 2; attempt += 1) {
      await tick();
    }
    assert.equal(fetchCalls.length, 2);
    await tick();

    assert.deepEqual(payloads, [validPayload]);
    assert.deepEqual(errors, []);
  } finally {
    controller.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("ignores an old response after the controller stops", async () => {
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
    clearInterval() {},
  };
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => {
      await responseReleased;
      return validPayload;
    },
  });

  const payloads = [];
  let settledCount = 0;
  const controller = createOiRefreshController({
    onPayload: payload => payloads.push(payload),
    onError: () => {},
    onSettled: () => {
      settledCount += 1;
    },
    refreshIntervalMs: 60_000,
  });

  try {
    controller.start();
    await tick();
    controller.stop();
    releaseResponse();
    await tick();
    await tick();

    assert.deepEqual(payloads, []);
    assert.equal(settledCount, 0);
  } finally {
    controller.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("does not refresh data freshness when payload application fails", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const previousPerformance = globalThis.performance;
  let clock = 0;
  let rejectPayload = false;

  globalThis.window = {
    setTimeout,
    clearTimeout,
    setInterval: () => 1,
    clearInterval() {},
  };
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => validPayload,
  });
  Object.defineProperty(globalThis, "performance", {
    configurable: true,
    value: { now: () => clock },
  });

  const originalDateNow = Date.now;
  Date.now = () => clock;
  const errors = [];
  const controller = createOiRefreshController({
    onPayload() {
      if (rejectPayload) throw new Error("payload application failed");
    },
    onError: (error, context) => errors.push({ error, context }),
    onSettled: () => {},
    refreshIntervalMs: 60_000,
    maxStaleMs: 10,
  });

  try {
    controller.start();
    await tick();
    await tick();

    clock = 20;
    rejectPayload = true;
    controller.refresh();
    await tick();
    await tick();

    assert.equal(errors.length, 1);
    assert.equal(errors[0].error.message, "payload application failed");
    assert.equal(errors[0].context.dataExpired, true);
  } finally {
    controller.dispose();
    Date.now = originalDateNow;
    Object.defineProperty(globalThis, "performance", {
      configurable: true,
      value: previousPerformance,
    });
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});
