import test from "node:test";
import assert from "node:assert/strict";

import { loadOiSnapshot } from "../realtime_oi_dashboard/static/js/features/oi/OiApiClient.js";

const validPayload = {
  schema_version: 7,
  active_symbols: [],
  total_symbols: 0,
  market_cap_loaded_symbols: 0,
  rows: [],
};

test("does not return an OI snapshot cancelled during response parsing", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  let releaseJson;
  let resolveJsonStarted;
  const jsonReleased = new Promise(resolve => {
    releaseJson = resolve;
  });
  const jsonStarted = new Promise(resolve => {
    resolveJsonStarted = resolve;
  });

  globalThis.window = { setTimeout, clearTimeout };
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => {
      resolveJsonStarted();
      await jsonReleased;
      return validPayload;
    },
  });

  const controller = new AbortController();
  try {
    const request = loadOiSnapshot({ signal: controller.signal });
    await jsonStarted;
    controller.abort();
    releaseJson();

    await assert.rejects(
      request,
      error => error?.code === "ABORTED"
        && error?.reason === "cancelled"
        && error?.message === "OI 請求已取消",
    );
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("does not start an OI fetch when already cancelled", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  let fetchCalls = 0;
  globalThis.window = { setTimeout, clearTimeout };
  globalThis.fetch = async () => {
    fetchCalls += 1;
    return { ok: true, json: async () => validPayload };
  };

  const controller = new AbortController();
  controller.abort();
  try {
    await assert.rejects(
      loadOiSnapshot({ signal: controller.signal }),
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
