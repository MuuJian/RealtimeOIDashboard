import test from "node:test";
import assert from "node:assert/strict";

import { createOiRefreshController } from "../realtime_oi_dashboard/static/js/services/OiRefreshController.js";

const validPayload = {
  schema_version: 7,
  active_symbols: [],
  total_symbols: 0,
  market_cap_loaded_symbols: 0,
  cvd_meta: {
    serviceHealth: "unavailable",
    universeSymbols: 0,
    desiredShards: 0,
    activeShards: 0,
    connectedShards: 0,
    incomingMessagesPerSecond: 0,
    processingLagMs: 0,
    backfillQueueSize: 0,
    healthCounts: {
      warming: 0,
      live: 0,
      stale: 0,
      partial: 0,
      unavailable: 0,
    },
  },
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
