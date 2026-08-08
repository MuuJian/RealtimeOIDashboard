import test from "node:test";
import assert from "node:assert/strict";

import { createLiveUpdateCoordinator } from "../realtime_oi_dashboard/static/js/services/LiveUpdateCoordinator.js";

function createHarness() {
  const calls = [];
  const controller = name => ({
    dispose: () => calls.push(`${name}.dispose`),
    start: () => calls.push(`${name}.start`),
    stop: () => calls.push(`${name}.stop`),
  });
  const oiRefresh = controller("oi");
  const signalScanRefresh = controller("signal");
  const priceFeed = {
    close: () => calls.push("price.close"),
    connect: () => calls.push("price.connect"),
  };
  const coordinator = createLiveUpdateCoordinator({
    oiRefresh,
    signalScanRefresh,
    priceFeed,
  });
  return { calls, coordinator };
}

test("runs only the selected page and ignores repeated tab selection", () => {
  const { calls, coordinator } = createHarness();

  coordinator.setPageActive(true);
  assert.deepEqual(calls, [
    "signal.stop",
    "price.connect",
    "oi.start",
  ]);

  calls.length = 0;
  coordinator.setSelectedPage("oi");
  assert.deepEqual(calls, []);

  coordinator.setSelectedPage("signalScan");
  assert.deepEqual(calls, [
    "oi.stop",
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
    "price.close",
  ]);

  calls.length = 0;
  coordinator.setPageActive(true);
  assert.deepEqual(calls, [
    "oi.stop",
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
    "price.close",
  ]);

  calls.length = 0;
  coordinator.setSelectedPage("signalScan");
  coordinator.setPageActive(false);
  coordinator.setPageActive(true);
  assert.deepEqual(calls, []);
});
