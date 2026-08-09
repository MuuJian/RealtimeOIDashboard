import test from "node:test";
import assert from "node:assert/strict";

import { createPageLifecycle } from "../realtime_oi_dashboard/static/js/services/PageLifecycle.js";

test("reports focus and visibility changes as one active state", () => {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  const fakeWindow = new EventTarget();
  const fakeDocument = new EventTarget();
  let focused = true;
  const states = [];

  fakeDocument.hidden = false;
  fakeDocument.visibilityState = "visible";
  fakeDocument.hasFocus = () => focused;
  globalThis.window = fakeWindow;
  globalThis.document = fakeDocument;

  const lifecycle = createPageLifecycle({
    onActiveChange: active => states.push(active),
    onDispose: () => {},
  });

  try {
    lifecycle.start();
    assert.deepEqual(states, [true]);

    focused = false;
    fakeWindow.dispatchEvent(new Event("blur"));
    focused = true;
    fakeWindow.dispatchEvent(new Event("focus"));
    fakeDocument.hidden = true;
    fakeDocument.visibilityState = "hidden";
    fakeDocument.dispatchEvent(new Event("visibilitychange"));

    assert.deepEqual(states, [true, false, true, false]);
  } finally {
    lifecycle.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("pauses for bfcache and resumes on pageshow without disposal", () => {
  const previousWindow = globalThis.window;
  const previousDocument = globalThis.document;
  const fakeWindow = new EventTarget();
  const fakeDocument = new EventTarget();
  const states = [];
  let disposeCount = 0;

  fakeDocument.hidden = false;
  fakeDocument.visibilityState = "visible";
  fakeDocument.hasFocus = () => true;
  globalThis.window = fakeWindow;
  globalThis.document = fakeDocument;

  const lifecycle = createPageLifecycle({
    onActiveChange: active => states.push(active),
    onDispose: () => {
      disposeCount += 1;
    },
  });

  try {
    lifecycle.start();
    const pageHide = new Event("pagehide");
    Object.defineProperty(pageHide, "persisted", { value: true });
    fakeWindow.dispatchEvent(pageHide);
    fakeWindow.dispatchEvent(new Event("pageshow"));

    assert.deepEqual(states, [true, false, true]);
    assert.equal(disposeCount, 0);
    assert.equal(lifecycle.isDisposed(), false);
  } finally {
    lifecycle.dispose();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
