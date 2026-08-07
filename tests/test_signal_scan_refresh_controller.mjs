import test from "node:test";
import assert from "node:assert/strict";

import { createSignalScanRefreshController } from "../realtime_oi_dashboard/static/js/services/SignalScanRefreshController.js";

const validPayload = {
  schema_version: 2,
  bulls: [],
  bears: [],
  spikes: [],
  saved_at: null,
  error: null,
  scan_total: 0,
  scan_succeeded: 0,
  partial: false,
  recent_errors: [],
};

function tick() {
  return new Promise(resolve => setTimeout(resolve, 0));
}

test("queues a fresh generation behind an asynchronously cancelled request", async () => {
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
  const controller = createSignalScanRefreshController({
    onPayload: payload => payloads.push(payload),
    onError: error => errors.push(error),
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

test("reports a timeout instead of treating it as a cancellation", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const activeIntervals = new Set();
  const errors = [];

  globalThis.window = {
    setTimeout(callback) {
      callback();
      return 1;
    },
    clearTimeout() {},
    setInterval(callback) {
      activeIntervals.add(callback);
      return callback;
    },
    clearInterval(callback) {
      activeIntervals.delete(callback);
    },
  };
  globalThis.fetch = async () => {
    throw new Error("fetch should not start after timeout");
  };

  const controller = createSignalScanRefreshController({
    onPayload: () => {},
    onError: error => errors.push(error),
    refreshIntervalMs: 60_000,
  });

  try {
    controller.start();
    await tick();
    assert.equal(errors.length, 1);
    assert.equal(errors[0].code, "ABORTED");
    assert.equal(errors[0].reason, "timeout");
  } finally {
    controller.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("exposes an invalidated callback context after stop", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const activeIntervals = new Set();
  let callbackStarted;
  let releaseCallback;
  const callbackReady = new Promise(resolve => {
    callbackStarted = resolve;
  });
  const callbackReleased = new Promise(resolve => {
    releaseCallback = resolve;
  });
  let committed = false;

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
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => validPayload,
  });

  const controller = createSignalScanRefreshController({
    onPayload: async (_payload, context) => {
      callbackStarted(context);
      await callbackReleased;
      if (context.isCurrent()) committed = true;
    },
    onError: () => {},
    refreshIntervalMs: 60_000,
  });

  try {
    controller.start();
    const context = await callbackReady;
    assert.equal(context.isCurrent(), true);
    controller.stop();
    assert.equal(context.signal.aborted, true);
    assert.equal(context.isCurrent(), false);
    releaseCallback();
    await tick();
    assert.equal(committed, false);
  } finally {
    controller.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("does not let a pending async payload callback block the next refresh", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const activeIntervals = new Set();
  const fetchCalls = [];
  let releaseCallback;
  const callbackReleased = new Promise(resolve => {
    releaseCallback = resolve;
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
  globalThis.fetch = async () => {
    fetchCalls.push(fetchCalls.length + 1);
    return {
      ok: true,
      json: async () => validPayload,
    };
  };

  const contexts = [];
  const controller = createSignalScanRefreshController({
    onPayload: async (_payload, context) => {
      contexts.push(context);
      await callbackReleased;
    },
    onError: () => {},
    refreshIntervalMs: 60_000,
  });

  try {
    controller.start();
    await tick();
    assert.equal(fetchCalls.length, 1);
    assert.equal(contexts.length, 1);

    const interval = [...activeIntervals][0];
    interval();
    await tick();
    assert.equal(fetchCalls.length, 2);
    assert.equal(contexts.length, 2);
    assert.equal(contexts[0].isCurrent(), false);
    assert.equal(contexts[1].isCurrent(), true);

    releaseCallback();
    await tick();
  } finally {
    controller.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("keeps an async error callback cancellable without blocking refresh", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const activeIntervals = new Set();
  const fetchCalls = [];
  const contexts = [];
  let releaseError;
  const errorReleased = new Promise(resolve => {
    releaseError = resolve;
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
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => validPayload,
  });

  const controller = createSignalScanRefreshController({
    onPayload: () => {
      fetchCalls.push(fetchCalls.length + 1);
      throw new Error("payload handler failed");
    },
    onError: async (_error, context) => {
      contexts.push(context);
      await errorReleased;
    },
    refreshIntervalMs: 60_000,
  });

  try {
    controller.start();
    await tick();
    assert.equal(fetchCalls.length, 1);
    assert.equal(contexts.length, 1);

    const interval = [...activeIntervals][0];
    interval();
    await tick();
    assert.equal(fetchCalls.length, 2);
    assert.equal(contexts.length, 2);
    assert.equal(contexts[0].isCurrent(), false);
    assert.equal(contexts[1].isCurrent(), true);

    controller.stop();
    assert.equal(contexts[1].signal.aborted, true);
    releaseError();
    await tick();
  } finally {
    controller.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});
