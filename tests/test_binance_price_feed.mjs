import test from "node:test";
import assert from "node:assert/strict";

import { createBinancePriceFeed } from "../realtime_oi_dashboard/static/js/data/BinancePriceFeed.js";


test("reconnects a stalled WebSocket handshake and retires the old socket", () => {
  const previousWindow = globalThis.window;
  const previousWebSocket = globalThis.WebSocket;
  const timers = new Map();
  const sockets = [];
  let nextTimer = 1;

  class FakeWebSocket {
    static CONNECTING = 0;
    static OPEN = 1;
    static CLOSING = 2;
    static CLOSED = 3;

    constructor() {
      this.readyState = FakeWebSocket.CONNECTING;
      sockets.push(this);
    }

    close() {
      if (this.readyState === FakeWebSocket.CONNECTING) {
        throw new Error("cannot close while connecting");
      }
      this.readyState = FakeWebSocket.CLOSING;
    }
  }

  globalThis.window = {
    setTimeout(callback, delay) {
      const id = nextTimer;
      nextTimer += 1;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    requestAnimationFrame() {
      throw new Error("no price flush expected");
    },
    cancelAnimationFrame() {},
  };
  globalThis.WebSocket = FakeWebSocket;

  const feed = createBinancePriceFeed();
  const statuses = [];
  feed.subscribeStatus(status => statuses.push(status));

  try {
    feed.connect();
    assert.equal(sockets.length, 1);
    runTimerWithDelay(timers, 15_000);

    assert.deepEqual(statuses, ["paused", "connecting", "error", "reconnecting"]);
    runTimerWithDelay(timers, 1_000);
    assert.equal(sockets.length, 2);

    sockets[0].readyState = FakeWebSocket.OPEN;
    sockets[0].onopen();
    assert.equal(sockets[0].readyState, FakeWebSocket.CLOSING);

    assert.doesNotThrow(() => feed.close());
    assert.equal(statuses.at(-1), "paused");
  } finally {
    feed.close();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousWebSocket === undefined) delete globalThis.WebSocket;
    else globalThis.WebSocket = previousWebSocket;
  }
});


function runTimerWithDelay(timers, delay) {
  const entry = [...timers.entries()].find(([, timer]) => timer.delay === delay);
  assert.ok(entry, `expected a ${delay}ms timer`);
  const [id, timer] = entry;
  timers.delete(id);
  timer.callback();
}
