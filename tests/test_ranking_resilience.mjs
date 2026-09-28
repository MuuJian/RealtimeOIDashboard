import test from "node:test";
import assert from "node:assert/strict";

import { createRankingProcessor } from "../realtime_oi_dashboard/static/js/services/RankingProcessor.js";
import { createRankingViewController } from "../realtime_oi_dashboard/static/js/services/RankingViewController.js";

const emptyView = {
  visibleSymbols: [],
  highOi7dSymbols: [],
  heatMax: {
    fundingRatePercent: 0,
    priceChangePercent: 0,
    price7dChangePercent: 0,
    oi24hChangePercent: 0,
    oi7dChangePercent: 0,
  },
};

test("fallback ranking errors reject asynchronously", async () => {
  const processor = createRankingProcessor();
  let request;
  try {
    assert.doesNotThrow(() => {
      request = processor.request({
        replaceRows: [],
        filters: null,
        sort: {},
        favorites: new Set(),
        signalFilters: {},
      });
    });
    await assert.rejects(request, TypeError);
  } finally {
    processor.dispose();
  }
});

test("worker failure rejects when the local fallback also fails", async () => {
  const previousWorker = globalThis.Worker;
  let worker = null;

  class FailingWorker {
    constructor() {
      worker = this;
    }

    postMessage() {}

    terminate() {}
  }

  globalThis.Worker = FailingWorker;
  const processor = createRankingProcessor();
  try {
    const request = processor.request({
      replaceRows: [],
      filters: null,
      sort: {},
      favorites: new Set(),
      signalFilters: {},
    });

    assert.ok(worker);
    assert.doesNotThrow(() => worker.onerror({ preventDefault() {} }));
    await assert.rejects(request, TypeError);
  } finally {
    processor.dispose();
    if (previousWorker === undefined) delete globalThis.Worker;
    else globalThis.Worker = previousWorker;
  }
});

test("ignores an obsolete ranking failure", async () => {
  const requests = [];
  const errors = [];
  const processor = {
    dispose() {},
    request() {
      return new Promise((resolve, reject) => requests.push({ resolve, reject }));
    },
  };
  const controller = createRankingViewController({
    processor,
    rankingData: { getRow: () => null },
    filters: { getState: () => ({}) },
    sort: { getState: () => ({}) },
    favorites: { getSet: () => new Set() },
    getSignalFilters: () => ({}),
    scheduleRender() {},
    onError: error => errors.push(error),
  });

  try {
    controller.request();
    controller.request();
    requests[0].reject(new Error("obsolete"));
    requests[1].resolve(emptyView);
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(errors, []);

    controller.request();
    requests[2].reject(new Error("current"));
    await Promise.resolve();
    await Promise.resolve();
    assert.deepEqual(errors.map(error => error.message), ["current"]);
  } finally {
    controller.dispose();
  }
});

test("coalesced ranking requests preserve every changed row and redraw request", async () => {
  const requests = [];
  const renders = [];
  const rows = new Map([
    ["BTCUSDT", { symbol: "BTCUSDT" }],
    ["ETHUSDT", { symbol: "ETHUSDT" }],
  ]);
  const view = { ...emptyView, visibleSymbols: [...rows.keys()] };
  const controller = createRankingViewController({
    processor: {
      dispose() {},
      request() {
        return new Promise(resolve => requests.push(resolve));
      },
    },
    rankingData: { getRow: symbol => rows.get(symbol) },
    filters: { getState: () => ({}) },
    sort: { getState: () => ({}) },
    favorites: { getSet: () => new Set() },
    getSignalFilters: () => ({}),
    scheduleRender: render => renders.push(render),
    onError: error => { throw error; },
  });

  try {
    controller.request({ replaceRows: [...rows.values()] });
    requests.shift()(view);
    await Promise.resolve();
    renders.length = 0;

    // The second tick arrives before the first worker response; neither tick
    // changes ranking order or heat maxima, so both cells must be patched.
    controller.request({ changedSymbols: ["BTCUSDT"] });
    controller.request({ changedSymbols: ["ETHUSDT"] });
    requests.shift()(view);
    requests.shift()(view);
    await Promise.resolve();
    assert.equal(renders.length, 1);
    assert.deepEqual([...renders[0].patchSymbols].sort(), ["BTCUSDT", "ETHUSDT"]);

    // An HTTP replacement must still redraw every visible cell if a price
    // tick overtakes it before the worker can finish.
    controller.request({ replaceRows: [...rows.values()], forceHigh: true });
    controller.request({ changedSymbols: ["ETHUSDT"] });
    requests.shift()(view);
    requests.shift()(view);
    await Promise.resolve();
    assert.equal(renders.at(-1).full, true);
    assert.equal(renders.at(-1).high, true);

    // Once applied, old redraw flags and symbols must not leak into later work.
    controller.request({ changedSymbols: ["BTCUSDT"] });
    requests.shift()(view);
    await Promise.resolve();
    assert.equal(renders.at(-1).full, false);
    assert.equal(renders.at(-1).high, false);
    assert.deepEqual([...renders.at(-1).patchSymbols], ["BTCUSDT"]);
  } finally {
    controller.dispose();
  }
});
