const FULL_FEATURES = Object.freeze({
  oi: true,
  cvd: true,
  signalScan: true,
  oiAlerts: true,
});

export function getRuntimeProfile(source = globalThis) {
  const config = source.__REALTIME_OI_DASHBOARD_CONFIG__;
  if (!config || (config.profile !== "full" && config.profile !== "stable")) {
    return Object.freeze({ profile: "full", features: FULL_FEATURES });
  }
  const features = config.features || {};
  return Object.freeze({
    profile: config.profile,
    features: Object.freeze({
      oi: true,
      cvd: features.cvd === true,
      signalScan: features.signalScan === true,
      oiAlerts: features.oiAlerts === true,
    }),
  });
}
