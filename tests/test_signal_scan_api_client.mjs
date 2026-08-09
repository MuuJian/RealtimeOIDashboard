import test from "node:test";
import assert from "node:assert/strict";

import { loadSignalScanSnapshot } from "../realtime_oi_dashboard/static/js/features/signal-scan/SignalScanApiClient.js";

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

test("does not return a snapshot when cancelled during response parsing", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  let resolveJsonStarted;
  let releaseJson;
  const jsonStarted = new Promise(resolve => {
    resolveJsonStarted = resolve;
  });
  const jsonReleased = new Promise(resolve => {
    releaseJson = resolve;
  });

  globalThis.window = {
    setTimeout,
    clearTimeout,
  };
  globalThis.fetch = async (_url, { signal }) => {
    assert.equal(signal.aborted, false);
    return {
      ok: true,
      json: async () => {
        resolveJsonStarted();
        await jsonReleased;
        return validPayload;
      },
    };
  };

  const requestController = new AbortController();
  try {
    const request = loadSignalScanSnapshot({ signal: requestController.signal });
    await jsonStarted;
    requestController.abort();
    releaseJson();

    await assert.rejects(
      request,
      error => error?.code === "ABORTED"
        && error?.reason === "cancelled"
        && error?.message === "訊號掃描請求已取消",
    );
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("does not start fetch when already cancelled", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.window = {
    setTimeout,
    clearTimeout,
  };
  globalThis.fetch = async () => {
    fetchCalls += 1;
    return { ok: true, json: async () => validPayload };
  };

  const requestController = new AbortController();
  requestController.abort();
  try {
    await assert.rejects(
      loadSignalScanSnapshot({ signal: requestController.signal }),
      error => error?.code === "ABORTED" && error?.reason === "cancelled",
    );
    assert.equal(fetchCalls, 0);
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});
