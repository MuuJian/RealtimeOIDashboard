import test from "node:test";
import assert from "node:assert/strict";

import { createOiAlertsPanel } from "../realtime_oi_dashboard/static/js/features/oi-alerts/OiAlertsPanel.js";

class FakeNode {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.textContent = "";
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.parentNode = null;
    this.listeners = new Map();
  }

  append(...nodes) {
    for (const node of nodes) {
      node.parentNode = this;
      this.children.push(node);
    }
  }

  replaceChildren(...nodes) {
    this.children = [];
    this.append(...nodes);
  }

  addEventListener(type, callback) {
    this.listeners.set(type, callback);
  }
}

function payload(overrides = {}) {
  return {
    config: { enabled: true, thresholds: [75e6, 100e6, 150e6] },
    telegram: {
      status: "unavailable",
      last_error: "connection refused",
      last_attempt_at: null,
    },
    active: [{
      symbol: "BTCUSDT",
      oi_value: 160e6,
      threshold: 150e6,
      signal: "High OI alert",
    }],
    events: [{
      symbol: "ETHUSDT",
      oi_value: 80e6,
      threshold: 75e6,
      signal: "Long entry",
      triggered_at: "2026-08-17T10:00:00Z",
      delivery_status: "failed",
    }],
    ...overrides,
  };
}

function createElements() {
  return {
    statusElement: new FakeNode("p"),
    signalLabelsElement: new FakeNode("p"),
    enabledInput: new FakeNode("input"),
    threshold75Input: new FakeNode("input"),
    threshold100Input: new FakeNode("input"),
    threshold150Input: new FakeNode("input"),
    saveButton: new FakeNode("button"),
    testButton: new FakeNode("button"),
    activeBody: new FakeNode("tbody"),
    eventsBody: new FakeNode("tbody"),
  };
}

test("renders fixed signal labels, active rows, and failed delivery events as text", () => {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });

  try {
    panel.render(payload());

    assert.equal(elements.signalLabelsElement.textContent, "75M: Long entry | 100M: Add position | 150M: High OI alert");
    assert.equal(elements.statusElement.textContent.includes("Telegram: unavailable"), true);
    assert.equal(elements.statusElement.textContent.includes("last attempt unavailable"), true);
    assert.equal(elements.threshold75Input.value, "75");
    assert.equal(elements.threshold100Input.value, "100");
    assert.equal(elements.threshold150Input.value, "150");
    assert.equal(elements.activeBody.children[0].children[0].textContent, "BTCUSDT");
    assert.equal(elements.eventsBody.children[0].children[5].textContent, "failed");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("keeps the last confirmed configuration visible when a save error renders", () => {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });

  try {
    panel.render(payload());
    elements.threshold75Input.value = "100";
    elements.threshold100Input.value = "75";
    panel.renderError(new Error("Invalid alert configuration"));

    assert.equal(elements.threshold75Input.value, "75");
    assert.equal(elements.threshold100Input.value, "100");
    assert.equal(elements.statusElement.textContent, "Invalid alert configuration");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("keeps fixed signal names paired with the saved threshold values", () => {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });

  try {
    panel.render(payload({
      config: { enabled: true, thresholds: [90e6, 120e6, 180e6] },
    }));

    assert.equal(elements.signalLabelsElement.textContent, "90M: Long entry | 120M: Add position | 180M: High OI alert");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
