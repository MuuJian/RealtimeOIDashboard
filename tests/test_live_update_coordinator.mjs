import test from "node:test";
import assert from "node:assert/strict";

import { createLiveUpdateCoordinator } from "../realtime_oi_dashboard/static/js/services/LiveUpdateCoordinator.js";
import { getDashboardElements } from "../realtime_oi_dashboard/static/js/data/DashboardElements.js";

function createHarness() {
  const calls = [];
  const controller = name => ({
    dispose: () => calls.push(`${name}.dispose`),
    start: () => calls.push(`${name}.start`),
    stop: () => calls.push(`${name}.stop`),
  });
  const oiRefresh = controller("oi");
  const signalScanRefresh = controller("signal");
  const oiAlertsRefresh = controller("alerts");
  const priceFeed = {
    close: () => calls.push("price.close"),
    connect: () => calls.push("price.connect"),
  };
  const coordinator = createLiveUpdateCoordinator({
    oiRefresh,
    signalScanRefresh,
    oiAlertsRefresh,
    priceFeed,
  });
  return { calls, coordinator };
}

test("runs only the selected page and ignores repeated tab selection", () => {
  const { calls, coordinator } = createHarness();

  coordinator.setPageActive(true);
  assert.deepEqual(calls, [
    "signal.stop",
    "alerts.stop",
    "price.connect",
    "oi.start",
  ]);

  calls.length = 0;
  coordinator.setSelectedPage("oi");
  assert.deepEqual(calls, []);

  coordinator.setSelectedPage("signalScan");
  assert.deepEqual(calls, [
    "oi.stop",
    "alerts.stop",
    "price.close",
    "signal.start",
  ]);
});

test("pauses every channel and restores only the selected page", () => {
  const { calls, coordinator } = createHarness();
  coordinator.setSelectedPage("signalScan");
  coordinator.setPageActive(true);

  calls.length = 0;
  coordinator.setPageActive(false);
  assert.deepEqual(calls, [
    "oi.stop",
    "signal.stop",
    "alerts.stop",
    "price.close",
  ]);

  calls.length = 0;
  coordinator.setPageActive(true);
  assert.deepEqual(calls, [
    "oi.stop",
    "alerts.stop",
    "price.close",
    "signal.start",
  ]);
});

test("does not restart channels after disposal", () => {
  const { calls, coordinator } = createHarness();
  coordinator.setPageActive(true);
  calls.length = 0;

  coordinator.dispose();
  assert.deepEqual(calls, [
    "oi.dispose",
    "signal.dispose",
    "alerts.dispose",
    "price.close",
  ]);

  calls.length = 0;
  coordinator.setSelectedPage("signalScan");
  coordinator.setPageActive(false);
  coordinator.setPageActive(true);
  assert.deepEqual(calls, []);
});

test("runs only OI alerts while the alerts tab is selected", () => {
  const { calls, coordinator } = createHarness();
  coordinator.setPageActive(true);

  calls.length = 0;
  coordinator.setSelectedPage("oiAlerts");
  assert.deepEqual(calls, [
    "oi.stop",
    "signal.stop",
    "price.close",
    "alerts.start",
  ]);

  calls.length = 0;
  coordinator.setSelectedPage("oi");
  assert.deepEqual(calls, [
    "signal.stop",
    "alerts.stop",
    "price.connect",
    "oi.start",
  ]);
});

test("pauses OI alerts when the page becomes inactive", () => {
  const { calls, coordinator } = createHarness();
  coordinator.setSelectedPage("oiAlerts");
  coordinator.setPageActive(true);

  calls.length = 0;
  coordinator.setPageActive(false);
  assert.deepEqual(calls, [
    "oi.stop",
    "signal.stop",
    "alerts.stop",
    "price.close",
  ]);
});

test("maps every OI alerts panel element", () => {
  const ids = new Map([
    ["tabOiAlerts", { id: "tabOiAlerts" }],
    ["oiAlertsPage", { id: "oiAlertsPage" }],
    ["oiAlertThreshold75", { id: "oiAlertThreshold75" }],
    ["oiAlertThreshold100", { id: "oiAlertThreshold100" }],
    ["oiAlertThreshold150", { id: "oiAlertThreshold150" }],
    ["oiAlertsTestMessage", { id: "oiAlertsTestMessage" }],
    ["oiAlertsActiveBody", { id: "oiAlertsActiveBody" }],
    ["oiAlertsEventsBody", { id: "oiAlertsEventsBody" }],
    ["oiAlertsStatus", { id: "oiAlertsStatus" }],
    ["oiAlertsSignalLabels", { id: "oiAlertsSignalLabels" }],
    ["oiAlertsEnabled", { id: "oiAlertsEnabled" }],
    ["oiAlertsScaleEnabled", { id: "oiAlertsScaleEnabled" }],
    ["oiAlertsSymbols", { id: "oiAlertsSymbols" }],
    ["oiAlertsWindowMinutes", { id: "oiAlertsWindowMinutes" }],
    ["oiAlertsMinOiChange", { id: "oiAlertsMinOiChange" }],
    ["oiAlertsMinPriceChange", { id: "oiAlertsMinPriceChange" }],
    ["oiAlertsCooldownMinutes", { id: "oiAlertsCooldownMinutes" }],
    ["oiAlertsRequireCvd", { id: "oiAlertsRequireCvd" }],
    ["oiAlertsSave", { id: "oiAlertsSave" }],
  ]);
  const root = {
    getElementById: id => ids.get(id) ?? null,
    querySelectorAll: () => [],
  };

  const elements = getDashboardElements(root);

  for (const key of [
    "tabOiAlerts",
    "oiAlertsPage",
    "oiAlertThreshold75",
    "oiAlertThreshold100",
    "oiAlertThreshold150",
    "oiAlertsTestMessage",
    "oiAlertsActiveBody",
    "oiAlertsEventsBody",
    "oiAlertsStatus",
    "oiAlertsSignalLabels",
    "oiAlertsEnabled",
    "oiAlertsScaleEnabled",
    "oiAlertsSymbols",
    "oiAlertsWindowMinutes",
    "oiAlertsMinOiChange",
    "oiAlertsMinPriceChange",
    "oiAlertsCooldownMinutes",
    "oiAlertsRequireCvd",
    "oiAlertsSave",
  ]) {
    assert.equal(elements[key], ids.get(key));
  }
});
