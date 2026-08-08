import test from "node:test";
import assert from "node:assert/strict";

import { createSignalScanPanel } from "../realtime_oi_dashboard/static/js/components/SignalScanPanel.js";

class FakeNode {
  constructor(tagName) {
    this.tagName = tagName;
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.textContent = "";
    this.className = "";
  }

  get firstChild() {
    return this.children[0] || null;
  }

  get nextSibling() {
    if (!this.parentNode) return null;
    const index = this.parentNode.children.indexOf(this);
    return this.parentNode.children[index + 1] || null;
  }

  append(...nodes) {
    for (const node of nodes) {
      node.remove();
      node.parentNode = this;
      this.children.push(node);
    }
  }

  insertBefore(node, current) {
    node.remove();
    node.parentNode = this;
    const index = current ? this.children.indexOf(current) : -1;
    if (index < 0) this.children.push(node);
    else this.children.splice(index, 0, node);
  }

  remove() {
    if (!this.parentNode) return;
    const index = this.parentNode.children.indexOf(this);
    if (index >= 0) this.parentNode.children.splice(index, 1);
    this.parentNode = null;
  }
}

function payload(overrides = {}) {
  return {
    bulls: [{
      symbol: "BTCUSDT",
      price: 100,
      chg1h: 1,
      chg24h: 2,
      aboveE20: 3,
      isBull: true,
      isBear: false,
      volRatio: 1,
    }],
    bears: [],
    spikes: [],
    saved_at: "2026-08-07T16:00:00+08:00",
    error: null,
    partial: false,
    scan_total: 1,
    scan_succeeded: 1,
    ...overrides,
  };
}

test("keeps the last signal rows visible when refresh fails", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {
    createElement: tagName => new FakeNode(tagName),
  };

  const bullsBody = new FakeNode("tbody");
  const bearsBody = new FakeNode("tbody");
  const spikesBody = new FakeNode("tbody");
  const statusEl = new FakeNode("div");
  const panel = createSignalScanPanel({
    bullsBody,
    bearsBody,
    spikesBody,
    statusEl,
  });

  try {
    panel.render(payload());
    const previousRow = bullsBody.firstChild;

    panel.renderError(new Error("temporary network failure"));

    assert.equal(bullsBody.firstChild, previousRow);
    assert.match(statusEl.textContent, /temporary network failure/);
    assert.match(statusEl.textContent, /上次掃描/);
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});

test("shows an explicit waiting state before the first scan", () => {
  const previousDocument = globalThis.document;
  globalThis.document = {
    createElement: tagName => new FakeNode(tagName),
  };

  const statusEl = new FakeNode("div");
  const panel = createSignalScanPanel({
    bullsBody: new FakeNode("tbody"),
    bearsBody: new FakeNode("tbody"),
    spikesBody: new FakeNode("tbody"),
    statusEl,
  });

  try {
    panel.render({
      bulls: [],
      bears: [],
      spikes: [],
      saved_at: null,
      error: null,
      partial: false,
      scan_total: 0,
      scan_succeeded: 0,
    });
    assert.equal(statusEl.textContent, "等待首次掃描");
  } finally {
    if (previousDocument === undefined) delete globalThis.document;
    else globalThis.document = previousDocument;
  }
});
