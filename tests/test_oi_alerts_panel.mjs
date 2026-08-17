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
    this.attributes = new Map();
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

  dispatch(type) {
    this.listeners.get(type)?.({ preventDefault() {} });
  }

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  getAttribute(name) {
    return this.attributes.get(name) || null;
  }
}

function sortButton(key) {
  const button = Object.assign(new FakeNode("button"), { dataset: { sortKey: key } });
  button.parentNode = new FakeNode("th");
  return button;
}

function payload(overrides = {}) {
  return {
    config: { enabled: true, thresholds: [75e6, 100e6, 150e6] },
    telegram: {
      status: "unavailable",
      last_error: "connection refused",
      last_attempt_at: null,
    },
    storage: { status: "load_error", last_error: "Saved alert state was invalid" },
    active: [{
      symbol: "BTCUSDT",
      oi_value: 160e6,
      threshold: 150e6,
      signal: "High OI alert",
      last_triggered_at: "2026-08-17T09:00:00Z",
    }],
    events: [{
      symbol: "ETHUSDT",
      oi_value: 80e6,
      threshold: 75e6,
      signal: "Long entry",
      triggered_at: "2026-08-17T10:00:00Z",
      delivery_status: "failed",
      failure_reason: "Telegram delivery failed",
      last_attempt_at: "2026-08-17T10:00:03Z",
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
    activeSortButtons: ["symbol", "oi_value", "threshold", "signal", "last_triggered_at"].map(sortButton),
    eventsSortButtons: ["symbol", "oi_value", "threshold", "signal", "triggered_at", "delivery_status", "failure_reason", "last_attempt_at"].map(sortButton),
  };
}

test("renders fixed signal labels, active rows, and failed delivery events as text", () => {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });
  panel.bind(new AbortController().signal);

  try {
    panel.render(payload());

    assert.equal(elements.signalLabelsElement.textContent, "75M：建立多單 | 100M：加倉 | 150M：高 OI 警示");
    assert.equal(elements.statusElement.textContent.includes("Telegram：無法使用"), true);
    assert.equal(elements.statusElement.textContent.includes("讀取失敗"), true);
    assert.equal(elements.statusElement.textContent.includes("最近嘗試：無法使用"), true);
    assert.equal(elements.threshold75Input.value, "75");
    assert.equal(elements.threshold100Input.value, "100");
    assert.equal(elements.threshold150Input.value, "150");
    assert.equal(elements.activeBody.children[0].children[0].textContent, "BTCUSDT");
    assert.equal(elements.activeBody.children[0].children[4].textContent, "2026-08-17T09:00:00Z");
    assert.equal(elements.eventsBody.children[0].children[5].textContent, "發送失敗");
    assert.equal(elements.eventsBody.children[0].children[6].textContent, "Telegram 發送失敗");
    assert.equal(elements.eventsBody.children[0].children[7].textContent, "2026-08-17T10:00:03Z");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("keeps unsaved threshold edits visible through refresh and save errors", () => {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });
  panel.bind(new AbortController().signal);

  try {
    panel.render(payload());
    elements.threshold75Input.value = "100";
    elements.threshold100Input.value = "75";
    elements.threshold75Input.dispatch("input");
    elements.threshold100Input.dispatch("input");
    panel.render(payload({
      config: { enabled: false, thresholds: [90e6, 120e6, 180e6] },
    }));
    panel.renderError(new Error("Invalid alert configuration"));

    assert.equal(elements.threshold75Input.value, "100");
    assert.equal(elements.threshold100Input.value, "75");
    assert.equal(elements.statusElement.textContent, "無法更新 OI 警報。請稍後再試。");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("refreshes only clean unfocused fields and clears edits after a confirmed save", async () => {
  const previousDocument = globalThis.document;
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  globalThis.window = { setTimeout, clearTimeout };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });
  panel.bind(new AbortController().signal);
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => payload({
      config: { enabled: false, thresholds: [95e6, 125e6, 185e6] },
    }),
  });

  try {
    panel.render(payload());
    elements.threshold75Input.value = "81";
    elements.threshold75Input.dispatch("input");
    elements.threshold100Input.dispatch("focus");

    panel.render(payload({
      config: { enabled: false, thresholds: [90e6, 120e6, 180e6] },
    }));

    assert.equal(elements.enabledInput.checked, false);
    assert.equal(elements.threshold75Input.value, "81");
    assert.equal(elements.threshold100Input.value, "100");
    assert.equal(elements.threshold150Input.value, "180");

    elements.threshold100Input.dispatch("blur");
    elements.saveButton.dispatch("click");
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(elements.threshold75Input.value, "95");
    assert.equal(elements.threshold100Input.value, "125");
    assert.equal(elements.threshold150Input.value, "185");

    panel.render(payload({
      config: { enabled: true, thresholds: [96e6, 126e6, 186e6] },
    }));
    assert.equal(elements.enabledInput.checked, true);
    assert.equal(elements.threshold75Input.value, "96");
    assert.equal(elements.threshold100Input.value, "126");
    assert.equal(elements.threshold150Input.value, "186");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
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

    assert.equal(elements.signalLabelsElement.textContent, "90M：建立多單 | 120M：加倉 | 180M：高 OI 警示");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("sorts OI alert tables by numeric, time, and text columns across refreshes", () => {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });
  panel.bind(new AbortController().signal);

  try {
    panel.render(payload({
      active: [
        { symbol: "ETHUSDT", oi_value: 80e6, threshold: 75e6, signal: "Long entry", last_triggered_at: "2026-08-17T08:00:00Z" },
        { symbol: "BTCUSDT", oi_value: 160e6, threshold: 150e6, signal: "High OI alert", last_triggered_at: "2026-08-17T09:00:00Z" },
      ],
      events: [
        { symbol: "ETHUSDT", oi_value: 80e6, threshold: 75e6, signal: "Long entry", triggered_at: "2026-08-17T09:00:00Z", delivery_status: "sent", failure_reason: null, last_attempt_at: "2026-08-17T09:00:01Z" },
        { symbol: "BTCUSDT", oi_value: 160e6, threshold: 150e6, signal: "High OI alert", triggered_at: "2026-08-17T10:00:00Z", delivery_status: "sent", failure_reason: null, last_attempt_at: "2026-08-17T10:00:01Z" },
      ],
    }));

    elements.activeSortButtons[1].dispatch("click");
    assert.equal(elements.activeBody.children[0].children[0].textContent, "BTCUSDT");
    assert.equal(elements.activeSortButtons[1].parentNode.getAttribute("aria-sort"), "descending");

    elements.activeSortButtons[1].dispatch("click");
    assert.equal(elements.activeBody.children[0].children[0].textContent, "ETHUSDT");
    assert.equal(elements.activeSortButtons[1].parentNode.getAttribute("aria-sort"), "ascending");

    elements.eventsSortButtons[4].dispatch("click");
    assert.equal(elements.eventsBody.children[0].children[0].textContent, "BTCUSDT");

    elements.eventsSortButtons[4].dispatch("click");
    assert.equal(elements.eventsBody.children[0].children[0].textContent, "ETHUSDT");

    elements.activeSortButtons[0].dispatch("click");
    assert.equal(elements.activeBody.children[0].children[0].textContent, "BTCUSDT");

    panel.render(payload({
      active: [
        { symbol: "ETHUSDT", oi_value: 81e6, threshold: 75e6, signal: "Long entry", last_triggered_at: "2026-08-17T08:00:00Z" },
        { symbol: "BTCUSDT", oi_value: 161e6, threshold: 150e6, signal: "High OI alert", last_triggered_at: "2026-08-17T09:00:00Z" },
      ],
      events: [
        { symbol: "BTCUSDT", oi_value: 160e6, threshold: 150e6, signal: "High OI alert", triggered_at: "2026-08-17T10:00:00Z", delivery_status: "sent", failure_reason: null, last_attempt_at: "2026-08-17T10:00:01Z" },
        { symbol: "ETHUSDT", oi_value: 80e6, threshold: 75e6, signal: "Long entry", triggered_at: "2026-08-17T09:00:00Z", delivery_status: "sent", failure_reason: null, last_attempt_at: "2026-08-17T09:00:01Z" },
      ],
    }));
    assert.equal(elements.activeBody.children[0].children[0].textContent, "BTCUSDT");
    assert.equal(elements.eventsBody.children[0].children[0].textContent, "ETHUSDT");
    assert.equal(elements.activeSortButtons[0].parentNode.getAttribute("aria-sort"), "ascending");
    assert.equal(elements.eventsSortButtons[4].parentNode.getAttribute("aria-sort"), "ascending");

    panel.render(payload({
      active: [
        { symbol: "BTCUSDT", oi_value: 161e6, threshold: 150e6, signal: "High OI alert", last_triggered_at: "2026-08-17T09:00:00Z" },
        { symbol: "ETHUSDT", oi_value: 81e6, threshold: 75e6, signal: "Long entry", last_triggered_at: "2026-08-17T08:00:00Z" },
      ],
    }));
    assert.equal(elements.activeBody.children[0].children[0].textContent, "BTCUSDT");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("renders OI Alerts labels, statuses, and signals in Traditional Chinese", () => {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });

  try {
    panel.render(payload());

    assert.equal(elements.signalLabelsElement.textContent, "75M：建立多單 | 100M：加倉 | 150M：高 OI 警示");
    assert.equal(elements.statusElement.textContent.includes("Telegram：無法使用"), true);
    assert.equal(elements.activeBody.children[0].children[3].textContent, "高 OI 警示");
    assert.equal(elements.eventsBody.children[0].children[3].textContent, "建立多單");
    assert.equal(elements.eventsBody.children[0].children[5].textContent, "發送失敗");

    panel.render(payload({
      storage: { status: "ok", last_error: null },
      telegram: { status: "sending", last_error: null, last_attempt_at: "2026-08-17T11:00:00Z" },
    }));
    assert.equal(elements.statusElement.textContent.includes("警報狀態：正常"), true);
    assert.equal(elements.statusElement.textContent.includes("Telegram：傳送中"), true);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
