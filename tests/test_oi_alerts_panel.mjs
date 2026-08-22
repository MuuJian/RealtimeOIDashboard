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

  focus() {}

  setAttribute(name, value) {
    this.attributes.set(name, value);
  }

  getAttribute(name) {
    return this.attributes.get(name) || null;
  }
}

const config = {
  enabled: true,
  thresholds: [75e6, 100e6, 150e6],
  scale_alerts_enabled: true,
  change_window_minutes: 15,
  min_oi_change_percent: 3,
  min_price_change_percent: 0.5,
  require_cvd_confirmation: false,
  cooldown_minutes: 30,
  symbols: [],
};

function sortButton(key) {
  const button = Object.assign(new FakeNode("button"), { dataset: { sortKey: key } });
  button.parentNode = new FakeNode("th");
  return button;
}

function activeRow(overrides = {}) {
  return {
    symbol: "BTCUSDT",
    event_type: "oi_expansion",
    oi_value: 160e6,
    threshold: 3,
    oi_change_percent: 4.2,
    price_change_percent: 1.1,
    signal: "Bullish OI expansion",
    explanation: "OI 15m +4.20%, price +1.10%",
    as_of: "2026-08-17T09:00:00Z",
    ...overrides,
  };
}

function eventRow(overrides = {}) {
  return {
    ...activeRow(),
    event_id: "event-1",
    threshold: 3,
    triggered_at: "2026-08-17T10:00:00Z",
    exchange_timestamp_ms: 1_787_327_400_000,
    delivery_status: "failed",
    failure_reason: "Telegram delivery failed",
    last_attempt_at: "2026-08-17T10:00:03Z",
    ...overrides,
  };
}

function payload(overrides = {}) {
  return {
    schema_version: 2,
    config,
    telegram: {
      status: "not_configured",
      last_error: null,
      last_attempt_at: null,
    },
    storage: { status: "ok", last_error: null },
    active: [activeRow()],
    events: [eventRow()],
    ...overrides,
  };
}

function createElements() {
  return {
    statusElement: new FakeNode("p"),
    signalLabelsElement: new FakeNode("p"),
    enabledInput: new FakeNode("input"),
    scaleEnabledInput: new FakeNode("input"),
    symbolsInput: new FakeNode("input"),
    windowMinutesInput: new FakeNode("input"),
    minOiChangeInput: new FakeNode("input"),
    minPriceChangeInput: new FakeNode("input"),
    cooldownMinutesInput: new FakeNode("input"),
    requireCvdInput: new FakeNode("input"),
    threshold75Input: new FakeNode("input"),
    threshold100Input: new FakeNode("input"),
    threshold150Input: new FakeNode("input"),
    saveButton: new FakeNode("button"),
    testButton: new FakeNode("button"),
    activeBody: new FakeNode("tbody"),
    eventsBody: new FakeNode("tbody"),
    activeSortButtons: ["symbol", "event_type", "oi_value", "oi_change_percent", "price_change_percent", "signal", "as_of"].map(sortButton),
    eventsSortButtons: ["triggered_at", "symbol", "event_type", "oi_value", "oi_change_percent", "price_change_percent", "signal", "delivery_status", "failure_reason"].map(sortButton),
  };
}

function installDocument() {
  const previousDocument = globalThis.document;
  globalThis.document = { createElement: tagName => new FakeNode(tagName) };
  return () => {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  };
}

test("renders neutral OI scale labels and directional signal context", () => {
  const restoreDocument = installDocument();
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });

  try {
    panel.render(payload());

    assert.match(elements.signalLabelsElement.textContent, /15m OI ≥ 3%/);
    assert.match(elements.signalLabelsElement.textContent, /75M：OI 規模提醒/);
    assert.equal(elements.windowMinutesInput.value, 15);
    assert.equal(elements.activeBody.children[0].children[1].textContent, "方向訊號");
    assert.equal(elements.activeBody.children[0].children[5].textContent, "多頭擴倉");
    assert.equal(elements.eventsBody.children[0].children[7].textContent, "發送失敗");
    assert.equal(elements.eventsBody.children[0].children[8].textContent, "Telegram 發送失敗");
  } finally {
    restoreDocument();
  }
});

test("preserves dirty rule edits and submits the complete configuration", async () => {
  const restoreDocument = installDocument();
  const previousWindow = globalThis.window;
  const previousFetch = globalThis.fetch;
  globalThis.window = { setTimeout, clearTimeout };
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });
  panel.bind(new AbortController().signal);
  const requests = [];
  globalThis.fetch = async (_url, options) => {
    requests.push(JSON.parse(options.body));
    return { ok: true, json: async () => payload() };
  };

  try {
    panel.render(payload());
    elements.minOiChangeInput.value = "5";
    elements.minOiChangeInput.dispatch("input");
    panel.render(payload({ config: { ...config, min_oi_change_percent: 4 } }));
    assert.equal(elements.minOiChangeInput.value, "5");

    elements.symbolsInput.value = "BTCUSDT, ETHUSDT";
    elements.saveButton.dispatch("click");
    await new Promise(resolve => setImmediate(resolve));

    assert.deepEqual(requests[0], {
      enabled: true,
      scale_alerts_enabled: true,
      change_window_minutes: 15,
      min_oi_change_percent: 5,
      min_price_change_percent: 0.5,
      require_cvd_confirmation: false,
      cooldown_minutes: 30,
      symbols: ["BTCUSDT", "ETHUSDT"],
      thresholds: [75e6, 100e6, 150e6],
    });
  } finally {
    restoreDocument();
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    if (previousFetch === undefined) delete globalThis.fetch;
    else globalThis.fetch = previousFetch;
  }
});

test("adds a Signal Scan symbol to the editable watchlist", () => {
  const restoreDocument = installDocument();
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });

  try {
    panel.render(payload({ config: { ...config, symbols: ["BTCUSDT"] } }));
    panel.addSymbol("ETHUSDT");
    panel.addSymbol("ETHUSDT");
    assert.equal(elements.symbolsInput.value, "BTCUSDT, ETHUSDT");
    assert.match(elements.statusElement.textContent, /請儲存規則/);
  } finally {
    restoreDocument();
  }
});

test("sorts active signals numerically and preserves the sort across refreshes", () => {
  const restoreDocument = installDocument();
  const elements = createElements();
  const panel = createOiAlertsPanel({ elements });
  panel.bind(new AbortController().signal);

  try {
    panel.render(payload({
      active: [
        activeRow({ symbol: "ETHUSDT", oi_change_percent: 3.2 }),
        activeRow({ symbol: "BTCUSDT", oi_change_percent: 6.4 }),
      ],
    }));
    elements.activeSortButtons[3].dispatch("click");
    assert.equal(elements.activeBody.children[0].children[0].textContent, "BTCUSDT");
    panel.render(payload({
      active: [
        activeRow({ symbol: "ETHUSDT", oi_change_percent: 7.1 }),
        activeRow({ symbol: "BTCUSDT", oi_change_percent: 4.3 }),
      ],
    }));
    assert.equal(elements.activeBody.children[0].children[0].textContent, "ETHUSDT");
  } finally {
    restoreDocument();
  }
});
