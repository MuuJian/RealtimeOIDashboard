import test from "node:test";
import assert from "node:assert/strict";

import { createHorizontalScrollControl } from "../realtime_oi_dashboard/static/js/components/HorizontalScrollControl.js";

test("horizontal control supports dragging, track clicks, and keyboard input", () => {
  const previousResizeObserver = globalThis.ResizeObserver;
  const observer = createObserverHarness();
  globalThis.ResizeObserver = observer.ResizeObserver;
  const viewport = createEventTarget({
    clientWidth: 600,
    firstElementChild: {},
    scrollLeft: 120,
    scrollWidth: 1800,
  });
  const thumb = {
    contains: () => false,
    style: {},
  };
  const track = createTrack({ clientWidth: 500 });
  const scrollElement = { hidden: true };
  const shell = { classList: createClassList() };

  try {
    const control = createHorizontalScrollControl({
      viewport,
      track,
      thumb,
      scrollElement,
      shell,
    });

    assert.equal(thumb.style.width, "167px");
    assert.match(thumb.style.transform, /^translateX\(33\.3/);
    assert.equal(track.attributes.get("aria-valuemax"), "1200");
    assert.equal(track.attributes.get("aria-valuenow"), "120");
    assert.equal(scrollElement.hidden, false);
    assert.equal(shell.classList.contains("is-scrollable"), true);
    assert.deepEqual(observer.observed, [
      viewport,
      track,
      viewport.firstElementChild,
    ]);

    track.emit("pointerdown", pointerEvent({
      clientX: 50,
      pointerId: 4,
      target: thumb,
    }));
    track.emit("pointermove", pointerEvent({
      clientX: 150,
      pointerId: 4,
      target: thumb,
    }));
    assert.ok(viewport.scrollLeft > 480 && viewport.scrollLeft < 481);
    assert.equal(track.classList.contains("is-dragging"), true);
    track.emit("pointerup", pointerEvent({
      clientX: 150,
      pointerId: 4,
      target: thumb,
    }));
    assert.equal(track.classList.contains("is-dragging"), false);

    track.emit("pointerdown", pointerEvent({
      clientX: 400,
      pointerId: 5,
      target: track,
    }));
    assert.ok(viewport.scrollLeft > 1140 && viewport.scrollLeft < 1141);
    track.emit("pointerup", pointerEvent({
      clientX: 400,
      pointerId: 5,
      target: track,
    }));

    track.emit("keydown", keyboardEvent("End"));
    assert.equal(viewport.scrollLeft, 1200);
    track.emit("keydown", keyboardEvent("Home"));
    assert.equal(viewport.scrollLeft, 0);
    track.emit("keydown", keyboardEvent("ArrowRight"));
    assert.equal(viewport.scrollLeft, 80);

    viewport.scrollLeft = 450;
    viewport.emit("scroll");
    assert.equal(track.attributes.get("aria-valuenow"), "450");
    assert.match(thumb.style.transform, /^translateX\(124\.8/);

    viewport.clientWidth = 1800;
    observer.callback();
    assert.equal(track.attributes.get("aria-valuemax"), "0");
    assert.equal(scrollElement.hidden, true);
    assert.equal(shell.classList.contains("is-scrollable"), false);

    control.dispose();
    assert.equal(observer.disconnected, true);
    track.emit("keydown", keyboardEvent("End"));
    assert.equal(viewport.scrollLeft, 450);
  } finally {
    if (previousResizeObserver === undefined) delete globalThis.ResizeObserver;
    else globalThis.ResizeObserver = previousResizeObserver;
  }
});

function createClassList() {
  const values = new Set();
  return {
    add(value) {
      values.add(value);
    },
    contains(value) {
      return values.has(value);
    },
    remove(value) {
      values.delete(value);
    },
    toggle(value, force) {
      if (force) values.add(value);
      else values.delete(value);
    },
  };
}

function createEventTarget(properties) {
  const listeners = new Map();
  return {
    ...properties,
    addEventListener(type, listener) {
      listeners.set(type, listener);
    },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) listeners.delete(type);
    },
    emit(type, event = {}) {
      listeners.get(type)?.(event);
    },
  };
}

function createTrack(properties) {
  const track = createEventTarget(properties);
  track.attributes = new Map();
  track.capturedPointers = new Set();
  track.classList = createClassList();
  track.focus = () => {};
  track.getBoundingClientRect = () => ({ left: 0 });
  track.hasPointerCapture = (pointerId) => (
    track.capturedPointers.has(pointerId)
  );
  track.releasePointerCapture = (pointerId) => {
    track.capturedPointers.delete(pointerId);
  };
  track.setAttribute = (name, value) => {
    track.attributes.set(name, value);
  };
  track.setPointerCapture = (pointerId) => {
    track.capturedPointers.add(pointerId);
  };
  return track;
}

function keyboardEvent(key) {
  return { key, preventDefault() {} };
}

function pointerEvent({ clientX, pointerId, target }) {
  return {
    button: 0,
    clientX,
    pointerId,
    preventDefault() {},
    target,
  };
}

function createObserverHarness() {
  const harness = {
    callback: null,
    disconnected: false,
    observed: [],
  };
  harness.ResizeObserver = class {
    constructor(callback) {
      harness.callback = callback;
    }

    observe(element) {
      harness.observed.push(element);
    }

    disconnect() {
      harness.disconnected = true;
    }
  };
  return harness;
}
