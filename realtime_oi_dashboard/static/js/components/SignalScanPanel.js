import { formatPercent, formatPrice, signClass } from "../utils/format.js";
import { syncChildren } from "../utils/dom.js";

export function createSignalScanPanel({ bullsBody, bearsBody, spikesBody, statusEl }) {
  const bullRows = new Map();
  const bearRows = new Map();
  const spikeRows = new Map();

  function render(payload) {
    renderTrendTable(bullsBody, bullRows, payload.bulls, "pos", "目前沒有符合條件的多頭標的。");
    renderTrendTable(bearsBody, bearRows, payload.bears, "neg", "目前沒有符合條件的空頭標的。");
    renderSpikeTable(spikesBody, spikeRows, payload.spikes);
    renderStatus(payload);
  }

  function renderError(error) {
    statusEl.textContent = error?.message || String(error);
  }

  function renderStatus(payload) {
    if (payload.error) {
      statusEl.textContent = payload.error;
      return;
    }
    const savedAt = payload.saved_at
      ? new Date(payload.saved_at).toLocaleTimeString("zh-TW", { hour12: false })
      : "-";
    statusEl.textContent = `上次掃描：${savedAt}`;
  }

  function renderTrendTable(tbody, rowsBySymbol, rows, strengthClass, emptyMessage) {
    if (!rows.length) {
      rowsBySymbol.clear();
      syncChildren(tbody, [createEmptyRow(6, emptyMessage)]);
      return;
    }

    const nextSymbols = new Set();
    const nextChildren = [];
    for (const row of rows) {
      nextSymbols.add(row.symbol);
      let tr = rowsBySymbol.get(row.symbol);
      if (!tr) {
        tr = createTrendRow();
        rowsBySymbol.set(row.symbol, tr);
      }
      updateTrendRow(tr, row, strengthClass);
      nextChildren.push(tr);
    }
    for (const symbol of rowsBySymbol.keys()) {
      if (!nextSymbols.has(symbol)) rowsBySymbol.delete(symbol);
    }
    syncChildren(tbody, nextChildren);
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

  function renderSpikeTable(tbody, rowsBySymbol, rows) {
    if (!rows.length) {
      rowsBySymbol.clear();
      syncChildren(tbody, [createEmptyRow(5, "目前沒有波動率突增的標的。")]);
      return;
    }

    const nextSymbols = new Set();
    const nextChildren = [];
    for (const row of rows) {
      nextSymbols.add(row.symbol);
      let tr = rowsBySymbol.get(row.symbol);
      if (!tr) {
        tr = createSpikeRow();
        rowsBySymbol.set(row.symbol, tr);
      }
      updateSpikeRow(tr, row);
      nextChildren.push(tr);
    }
    for (const symbol of rowsBySymbol.keys()) {
      if (!nextSymbols.has(symbol)) rowsBySymbol.delete(symbol);
    }
    syncChildren(tbody, nextChildren);
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

  function createEmptyRow(colspan, message) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = colspan;
    td.className = "empty";
    td.textContent = message;
    tr.append(td);
    return tr;
  }

  return { render, renderError };
}
