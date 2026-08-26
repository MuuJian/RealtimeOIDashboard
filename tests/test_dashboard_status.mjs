import assert from "node:assert/strict";
import test from "node:test";

import { createDashboardStatus } from "../realtime_oi_dashboard/static/js/components/DashboardStatus.js";

test("dashboard status pauses the live clock while the page is hidden", () => {
  const originalWindow = globalThis.window;
  const activeTimers = new Set();
  let nextTimer = 1;
  globalThis.window = {
    setInterval() {
      const timer = nextTimer;
      nextTimer += 1;
      activeTimers.add(timer);
      return timer;
    },
    clearInterval(timer) {
      activeTimers.delete(timer);
    },
  };

  const title = element();
  const detail = element();
  const status = createDashboardStatus({
    title,
    detail,
    oiLoaded: element(),
    marketCapLoaded: element(),
  });

  try {
    status.renderPayload({
      rows: [{}],
      error: null,
      recent_errors: [],
      saved_at: "2026-08-26T00:00:00Z",
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
    assert.equal(detail.textContent, "offline");

    status.setPaused(true);
    status.setPaused(false);
    assert.equal(activeTimers.size, 0);
  } finally {
    status.dispose();
    globalThis.window = originalWindow;
  }
});

function element() {
  return { textContent: "", title: "" };
}
