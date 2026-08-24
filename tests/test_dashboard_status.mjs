import test from "node:test";
import assert from "node:assert/strict";

import { createDashboardStatus } from "../realtime_oi_dashboard/static/js/components/DashboardStatus.js";

test("pauses the live clock while hidden and resumes only valid payloads", () => {
  const previousWindow = globalThis.window;
  const activeTimers = new Set();
  globalThis.window = {
    setInterval(callback) {
      activeTimers.add(callback);
      return callback;
    },
    clearInterval(callback) {
      activeTimers.delete(callback);
    },
  };
  const elements = {
    title: element(),
    detail: element(),
    oiLoaded: element(),
    marketCapLoaded: element(),
  };
  const status = createDashboardStatus(elements);

  try {
    status.renderPayload({
      rows: [{}],
      error: null,
      recent_errors: [],
      saved_at: "2026-08-24T12:00:00+08:00",
      total_symbols: 1,
      market_cap_loaded_symbols: 1,
    });
    assert.equal(activeTimers.size, 1);

    status.setPaused(true);
    assert.equal(activeTimers.size, 0);

    status.setPaused(false);
    assert.equal(activeTimers.size, 1);

    status.renderConnectionError(new Error("offline"));
    assert.equal(activeTimers.size, 0);
    assert.equal(elements.detail.textContent, "offline");

    status.setPaused(true);
    status.setPaused(false);
    assert.equal(activeTimers.size, 0);
    assert.equal(elements.detail.textContent, "offline");
  } finally {
    status.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});

function element() {
  return { textContent: "", title: "" };
}
