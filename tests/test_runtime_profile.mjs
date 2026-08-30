import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { getRuntimeProfile } from "../realtime_oi_dashboard/static/js/config/RuntimeProfile.js";

const dashboardSource = readFileSync(
  new URL("../realtime_oi_dashboard/static/js/dashboard.js", import.meta.url),
  "utf8",
);

test("runtime profile defaults to the existing full experience", () => {
  const profile = getRuntimeProfile({});

  assert.equal(profile.profile, "full");
  assert.deepEqual(profile.features, {
    oi: true,
    cvd: true,
    signalScan: true,
    oiAlerts: true,
  });
});

test("stable runtime profile exposes only OI", () => {
  const profile = getRuntimeProfile({
    __REALTIME_OI_DASHBOARD_CONFIG__: {
      profile: "stable",
      features: {
        oi: true,
        cvd: false,
        signalScan: false,
        oiAlerts: false,
      },
    },
  });

  assert.deepEqual(profile.features, {
    oi: true,
    cvd: false,
    signalScan: false,
    oiAlerts: false,
  });
});

test("optional profile modules load only when their feature is enabled", () => {
  assert.doesNotMatch(
    dashboardSource,
    /^import .*\.\/features\/(?:signal-scan|oi-alerts)\//m,
  );
  assert.match(
    dashboardSource,
    /import\("\.\/features\/signal-scan\/SignalScanPanel\.js"\)/,
  );
  assert.match(
    dashboardSource,
    /import\("\.\/features\/oi-alerts\/OiAlertsPanel\.js"\)/,
  );
});
