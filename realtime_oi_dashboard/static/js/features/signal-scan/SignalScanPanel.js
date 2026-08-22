import {
  binanceFuturesUrl,
  formatFundingRate,
  formatPercent,
  formatPrice,
  formatUtc8Time,
  signClass,
} from "../../utils/format.js";
import { syncChildren } from "../../utils/dom.js";

export function createSignalScanPanel({
  bullsBody,
  bearsBody,
  spikesBody,
  statusEl,
  onCreateAlert = () => {},
}) {
  let lastPayload = null;
  const bullTable = createRowRenderer({
    tbody: bullsBody,
    colspan: 10,
    emptyMessage: "目前沒有符合條件的多頭標的。",
    createRow: createTrendRow,
    updateRow: (tr, row) => updateTrendRow(tr, row, onCreateAlert),
  });
  const bearTable = createRowRenderer({
    tbody: bearsBody,
    colspan: 10,
    emptyMessage: "目前沒有符合條件的空頭標的。",
    createRow: createTrendRow,
    updateRow: (tr, row) => updateTrendRow(tr, row, onCreateAlert),
  });
  const spikeTable = createRowRenderer({
    tbody: spikesBody,
    colspan: 10,
    emptyMessage: "目前沒有波動率突增的標的。",
    createRow: createSpikeRow,
    updateRow: (tr, row) => updateSpikeRow(tr, row, onCreateAlert),
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
    const oiChangeCell = document.createElement("td");
    const cvdCell = document.createElement("td");
    const fundingCell = document.createElement("td");
    const aboveE20Cell = document.createElement("td");
    const reasonCell = document.createElement("td");
    reasonCell.className = "signal-reason";
    const actionCell = document.createElement("td");
    const actionButton = createAlertButton();
    actionCell.append(actionButton);
    tr.append(
      symbolCell,
      priceCell,
      chg1hCell,
      chg24hCell,
      oiChangeCell,
      cvdCell,
      fundingCell,
      aboveE20Cell,
      reasonCell,
      actionCell,
    );
    tr._cells = {
      symbolCell,
      priceCell,
      chg1hCell,
      chg24hCell,
      oiChangeCell,
      cvdCell,
      fundingCell,
      aboveE20Cell,
      reasonCell,
      actionButton,
    };
    return tr;
  }

  function updateTrendRow(tr, row, createAlert) {
    const {
      symbolCell,
      priceCell,
      chg1hCell,
      chg24hCell,
      oiChangeCell,
      cvdCell,
      fundingCell,
      aboveE20Cell,
      reasonCell,
      actionButton,
    } = tr._cells;
    renderSymbolLink(symbolCell, row.symbol);
    priceCell.textContent = formatPrice(row.price);
    chg1hCell.textContent = formatPercent(row.chg1h);
    chg1hCell.className = signClass(row.chg1h);
    chg24hCell.textContent = formatPercent(row.chg24h);
    chg24hCell.className = signClass(row.chg24h);
    aboveE20Cell.textContent = formatPercent(row.aboveE20);
    aboveE20Cell.className = signClass(row.aboveE20);
    renderContextCells({ oiChangeCell, cvdCell, fundingCell, reasonCell }, row);
    bindAlertButton(actionButton, row.symbol, createAlert);
  }

  function createSpikeRow() {
    const tr = document.createElement("tr");
    const symbolCell = document.createElement("td");
    symbolCell.className = "symbol";
    const priceCell = document.createElement("td");
    const chg1hCell = document.createElement("td");
    const chg24hCell = document.createElement("td");
    const volRatioCell = document.createElement("td");
    const oiChangeCell = document.createElement("td");
    const cvdCell = document.createElement("td");
    const fundingCell = document.createElement("td");
    const reasonCell = document.createElement("td");
    reasonCell.className = "signal-reason";
    const actionCell = document.createElement("td");
    const actionButton = createAlertButton();
    actionCell.append(actionButton);
    tr.append(
      symbolCell,
      priceCell,
      chg1hCell,
      chg24hCell,
      volRatioCell,
      oiChangeCell,
      cvdCell,
      fundingCell,
      reasonCell,
      actionCell,
    );
    tr._cells = {
      symbolCell,
      priceCell,
      chg1hCell,
      chg24hCell,
      volRatioCell,
      oiChangeCell,
      cvdCell,
      fundingCell,
      reasonCell,
      actionButton,
    };
    return tr;
  }

  function updateSpikeRow(tr, row, createAlert) {
    const {
      symbolCell,
      priceCell,
      chg1hCell,
      chg24hCell,
      volRatioCell,
      oiChangeCell,
      cvdCell,
      fundingCell,
      reasonCell,
      actionButton,
    } = tr._cells;
    renderSymbolLink(symbolCell, row.symbol);
    priceCell.textContent = formatPrice(row.price);
    chg1hCell.textContent = formatPercent(row.chg1h);
    chg1hCell.className = signClass(row.chg1h);
    chg24hCell.textContent = formatPercent(row.chg24h);
    chg24hCell.className = signClass(row.chg24h);
    volRatioCell.textContent = `${row.volRatio.toFixed(1)}×`;
    renderContextCells({ oiChangeCell, cvdCell, fundingCell, reasonCell }, row);
    bindAlertButton(actionButton, row.symbol, createAlert);
  }

  function formatSavedAt(value) {
    if (!value) return "-";
    return formatUtc8Time(value) || "-";
  }

  return { render, renderError };
}

function renderContextCells({ oiChangeCell, cvdCell, fundingCell, reasonCell }, row) {
  oiChangeCell.textContent = formatPercent(row.oiChangePercent);
  oiChangeCell.className = signClass(row.oiChangePercent);
  cvdCell.textContent = row.cvd15mRatio == null
    ? "-"
    : formatPercent(row.cvd15mRatio * 100);
  cvdCell.className = signClass(row.cvd15mRatio);
  fundingCell.textContent = formatFundingRate(row.fundingRatePercent);
  fundingCell.className = signClass(row.fundingRatePercent);
  reasonCell.textContent = row.signalReason || "等待 OI 窗口資料";
}

function renderSymbolLink(cell, symbol) {
  let link = cell.firstElementChild;
  if (!link) {
    link = document.createElement("a");
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    cell.append(link);
  }
  link.href = binanceFuturesUrl(symbol);
  link.textContent = symbol.replace("USDT", "");
}

function createAlertButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "signal-alert-action";
  button.textContent = "加入監控";
  return button;
}

function bindAlertButton(button, symbol, onCreateAlert) {
  button.onclick = () => onCreateAlert(symbol);
  button.setAttribute?.("aria-label", `將 ${symbol} 加入 OI 警報監控`);
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
