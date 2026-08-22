import test from "node:test";
import assert from "node:assert/strict";

import { loadOiSnapshot } from "../realtime_oi_dashboard/static/js/features/oi/OiApiClient.js";
import { loadSignalScanSnapshot } from "../realtime_oi_dashboard/static/js/features/signal-scan/SignalScanApiClient.js";

const oiPayload = {
  schema_version: 7,
  active_symbols: [],
  total_symbols: 0,
  market_cap_loaded_symbols: 0,
  oi_dominance_history: [],
  cvd_meta: {
    serviceHealth: "unavailable",
    universeSymbols: 0,
    desiredShards: 0,
    activeShards: 0,
    connectedShards: 0,
    backfillQueueSize: 0,
    incomingMessagesPerSecond: 0,
    processingLagMs: 0,
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

const signalPayload = {
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

test("API clients allow browser cache revalidation", async () => {
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.window = { setTimeout, clearTimeout };
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      json: async () => url === "/api/oi" ? oiPayload : signalPayload,
    };
  };

  try {
    await loadOiSnapshot();
    await loadSignalScanSnapshot();
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }

  assert.deepEqual(requests.map(({ url, options }) => ({
    url,
    cache: options.cache,
  })), [
    { url: "/api/oi", cache: "no-cache" },
    { url: "/api/signal-scan", cache: "no-cache" },
  ]);
});
