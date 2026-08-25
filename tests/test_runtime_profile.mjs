import assert from "node:assert/strict";
import test from "node:test";

import { getRuntimeProfile } from "../realtime_oi_dashboard/static/js/config/RuntimeProfile.js";

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
