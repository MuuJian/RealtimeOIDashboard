import {
  formatPercent,
  formatPrice,
  formatUtc8Time,
  signClass,
} from "../../utils/format.js";
import { syncChildren } from "../../utils/dom.js";

export function createSignalScanPanel({ bullsBody, bearsBody, spikesBody, statusEl }) {
  let lastPayload = null;
  const bullTable = createRowRenderer({
    tbody: bullsBody,
    colspan: 6,
    emptyMessage: "目前沒有符合條件的多頭標的。",
    createRow: createTrendRow,
    updateRow: (tr, row) => updateTrendRow(tr, row, "pos"),
  });
  const bearTable = createRowRenderer({
    tbody: bearsBody,
    colspan: 6,
    emptyMessage: "目前沒有符合條件的空頭標的。",
    createRow: createTrendRow,
    updateRow: (tr, row) => updateTrendRow(tr, row, "neg"),
  });
  const spikeTable = createRowRenderer({
    tbody: spikesBody,
    colspan: 5,
    emptyMessage: "目前沒有波動率突增的標的。",
    createRow: createSpikeRow,
    updateRow: updateSpikeRow,
  });

  function render(payload) {
    bullTable.render(payload.bulls);
    bearTable.render(payload.bears);
    spikeTable.render(payload.spikes);
    lastPayload = payload;
    renderStatus(payload);
  }

  function renderError(error) {
    const message = error?.message || String(error);
    const savedAt = formatSavedAt(lastPayload?.saved_at);
    statusEl.textContent = lastPayload?.saved_at
      ? `刷新失敗：${message}；上次掃描：${savedAt}`
      : `刷新失敗：${message}`;
  }

  function renderStatus(payload) {
    if (payload.error) {
      const coverage = payload.partial
        ? `（${payload.scan_succeeded}/${payload.scan_total}）`
        : "";
      statusEl.textContent = `${payload.error}${coverage}`;
      return;
    }
    if (!payload.saved_at && payload.scan_total === 0) {
      statusEl.textContent = "等待首次掃描";
      return;
    }
    const savedAt = formatSavedAt(payload.saved_at);
    if (payload.partial) {
      statusEl.textContent = (
        `本次掃描部分完成（${payload.scan_succeeded}/${payload.scan_total}），`
        + `更新時間：${savedAt}`
      );
      return;
    }
    statusEl.textContent = `上次掃描：${savedAt}`;
  }

  function createTrendRow() {
    const tr = document.createElement("tr");
    const symbolCell = document.createElement("td");
    symbolCell.className = "symbol";
    const priceCell = document.createElement("td");
    const chg1hCell = document.createElement("td");
    const chg24hCell = document.createElement("td");
    const aboveE20Cell = document.createElement("td");
    const strengthCell = document.createElement("td");
    const strengthBar = document.createElement("span");
    strengthBar.className = "strength-bar";
    strengthCell.append(strengthBar);
    tr.append(symbolCell, priceCell, chg1hCell, chg24hCell, aboveE20Cell, strengthCell);
    tr._cells = { symbolCell, priceCell, chg1hCell, chg24hCell, aboveE20Cell, strengthBar };
    return tr;
  }

  function updateTrendRow(tr, row, strengthClass) {
    const { symbolCell, priceCell, chg1hCell, chg24hCell, aboveE20Cell, strengthBar } = tr._cells;
    symbolCell.textContent = row.symbol.replace("USDT", "");
    priceCell.textContent = formatPrice(row.price);
    chg1hCell.textContent = formatPercent(row.chg1h);
    chg1hCell.className = signClass(row.chg1h);
    chg24hCell.textContent = formatPercent(row.chg24h);
    chg24hCell.className = signClass(row.chg24h);
    aboveE20Cell.textContent = formatPercent(row.aboveE20);
    aboveE20Cell.className = signClass(row.aboveE20);
    const width = Math.min(60, Math.max(4, Math.abs(row.aboveE20) * 8));
    strengthBar.style.width = `${width.toFixed(0)}px`;
    strengthBar.className = `strength-bar ${strengthClass}`;
  }

  function createSpikeRow() {
    const tr = document.createElement("tr");
    const symbolCell = document.createElement("td");
    symbolCell.className = "symbol";
    const priceCell = document.createElement("td");
    const chg1hCell = document.createElement("td");
    const chg24hCell = document.createElement("td");
    const volRatioCell = document.createElement("td");
    tr.append(symbolCell, priceCell, chg1hCell, chg24hCell, volRatioCell);
    tr._cells = { symbolCell, priceCell, chg1hCell, chg24hCell, volRatioCell };
    return tr;
  }

  function updateSpikeRow(tr, row) {
    const { symbolCell, priceCell, chg1hCell, chg24hCell, volRatioCell } = tr._cells;
    symbolCell.textContent = row.symbol.replace("USDT", "");
    priceCell.textContent = formatPrice(row.price);
    chg1hCell.textContent = formatPercent(row.chg1h);
    chg1hCell.className = signClass(row.chg1h);
    chg24hCell.textContent = formatPercent(row.chg24h);
    chg24hCell.className = signClass(row.chg24h);
    volRatioCell.textContent = `${row.volRatio.toFixed(1)}×`;
  }

  function formatSavedAt(value) {
    if (!value) return "-";
    return formatUtc8Time(value) || "-";
  }

  return { render, renderError };
}

function createRowRenderer({
  tbody,
  colspan,
  emptyMessage,
  createRow,
  updateRow,
}) {
  const rowsBySymbol = new Map();
  const emptyRow = createEmptyRow(colspan, emptyMessage);

  function render(rows) {
    if (!Array.isArray(rows) || !rows.length) {
      clear();
      return;
    }

    const nextSymbols = new Set();
    const nextChildren = [];
    for (const row of rows) {
      if (!row || typeof row.symbol !== "string" || nextSymbols.has(row.symbol)) {
        continue;
      }
      nextSymbols.add(row.symbol);
      let tr = rowsBySymbol.get(row.symbol);
      if (!tr) {
        tr = createRow();
        rowsBySymbol.set(row.symbol, tr);
      }
      updateRow(tr, row);
      nextChildren.push(tr);
    }

    if (!nextChildren.length) {
      clear();
      return;
    }

    for (const [symbol, tr] of rowsBySymbol.entries()) {
      if (!nextSymbols.has(symbol)) {
        tr.remove();
        rowsBySymbol.delete(symbol);
      }
    }
    syncChildren(tbody, nextChildren);
  }

  function clear() {
    rowsBySymbol.clear();
    syncChildren(tbody, [emptyRow]);
  }

  return { clear, render };
}

function createEmptyRow(colspan, message) {
  const tr = document.createElement("tr");
  const td = document.createElement("td");
  td.colSpan = colspan;
  td.className = "empty";
  td.textContent = message;
  tr.append(td);
  return tr;
}
