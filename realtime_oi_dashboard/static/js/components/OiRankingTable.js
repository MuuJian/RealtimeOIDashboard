import { createRankingRow, updateRankingRow } from "./OiRankingRow.js";
import { syncChildren } from "../utils/dom.js";

const LOADING_MESSAGE =
  "正在獲取本次啟動後的 OI 數據，結果會按批次逐步出現。";
const FILTERED_EMPTY_MESSAGE = "暫無符合當前篩選條件的幣種。";
const COLUMN_COUNT = 15;
const OVERSCAN_ROWS = 6;
const DEFAULT_ROW_HEIGHT = 55;

export function createOiRankingTable({ tbody, getRowBySymbol }) {
  const rowsBySymbol = new Map();
  const viewport = tbody.closest(".table-wrap");
  const tableElement = tbody.closest("table");
  const topSpacer = createSpacer();
  const bottomSpacer = createSpacer();
  let rows = [];
  let latestContext = null;
  let renderedStart = -1;
  let renderedEnd = -1;
  let renderFrame = 0;
  let disposed = false;
  const resizeObserver = typeof ResizeObserver === "function"
    ? new ResizeObserver(scheduleWindowRender)
    : null;

  viewport.addEventListener("scroll", scheduleWindowRender, { passive: true });
  if (resizeObserver) {
    resizeObserver.observe(viewport);
  } else {
    window.addEventListener("resize", scheduleWindowRender);
  }

  function render(nextRows, context) {
    rows = nextRows;
    latestContext = context;
    tableElement?.setAttribute("aria-rowcount", String(rows.length + 1));

    if (!rows.length) {
      clearTrackedRows();
      tbody.textContent = "";
      tbody.append(createEmptyRow(context.hasSourceRows));
      renderedStart = 0;
      renderedEnd = 0;
      return [];
    }

    clampScrollPosition();
    return renderWindow(true);
  }

  function patchRows(symbols, context) {
    latestContext = context;
    for (const symbol of symbols) {
      const tr = rowsBySymbol.get(symbol);
      const row = getRowBySymbol(symbol);
      if (tr && row) {
        updateRankingRow(tr, row, context);
      }
    }
  }

  function renderWindow(force = false) {
    if (disposed || !rows.length || !latestContext) return [];

    const { start, end, rowHeight } = getRenderRange();
    if (!force && start === renderedStart && end === renderedEnd) return [];

    const nextSymbols = new Set();
    const createdRows = [];
    const nextChildren = [topSpacer];
    setSpacerHeight(topSpacer, start * rowHeight);

    for (let index = start; index < end; index += 1) {
      const row = rows[index];
      nextSymbols.add(row.symbol);

      let tr = rowsBySymbol.get(row.symbol);
      if (!tr) {
        tr = createRankingRow(row, latestContext);
        rowsBySymbol.set(row.symbol, tr);
        createdRows.push(tr);
      } else {
        updateRankingRow(tr, row, latestContext);
      }
      tr.setAttribute("aria-rowindex", String(index + 2));
      nextChildren.push(tr);
    }

    setSpacerHeight(bottomSpacer, (rows.length - end) * rowHeight);
    nextChildren.push(bottomSpacer);
    for (const [symbol, tr] of rowsBySymbol.entries()) {
      if (nextSymbols.has(symbol)) continue;
      tr.remove();
      rowsBySymbol.delete(symbol);
    }

    syncChildren(tbody, nextChildren);
    renderedStart = start;
    renderedEnd = end;
    return createdRows;
  }

  function getRenderRange() {
    const rowHeight = getRowHeight();
    const headerHeight = tableElement?.tHead?.getBoundingClientRect().height || 0;
    const bodyScrollTop = Math.max(0, viewport.scrollTop - headerHeight);
    const firstVisible = Math.floor(bodyScrollTop / rowHeight);
    const visibleCount = Math.ceil(viewport.clientHeight / rowHeight);
    const start = Math.max(0, firstVisible - OVERSCAN_ROWS);
    const end = Math.min(
      rows.length,
      firstVisible + visibleCount + OVERSCAN_ROWS,
    );
    return { start, end, rowHeight };
  }

  function getRowHeight() {
    const value = tableElement
      ? Number.parseFloat(
        getComputedStyle(tableElement).getPropertyValue("--virtual-row-height"),
      )
      : NaN;
    return Number.isFinite(value) && value > 0 ? value : DEFAULT_ROW_HEIGHT;
  }

  function clampScrollPosition() {
    const rowHeight = getRowHeight();
    const headerHeight = tableElement?.tHead?.getBoundingClientRect().height || 0;
    const maxScrollTop = Math.max(
      0,
      headerHeight + rows.length * rowHeight - viewport.clientHeight,
    );
    if (viewport.scrollTop > maxScrollTop) {
      viewport.scrollTop = maxScrollTop;
    }
  }

  function scheduleWindowRender() {
    if (disposed || renderFrame) return;
    renderFrame = window.requestAnimationFrame(() => {
      renderFrame = 0;
      renderWindow();
    });
  }

  function scrollToTop() {
    viewport.scrollTop = 0;
    renderedStart = -1;
    renderedEnd = -1;
  }

  function createSpacer() {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    tr.className = "virtual-spacer";
    tr.setAttribute("aria-hidden", "true");
    td.colSpan = COLUMN_COUNT;
    tr.append(td);
    return tr;
  }

  function setSpacerHeight(spacer, height) {
    spacer.hidden = height <= 0;
    spacer.firstElementChild.style.height = `${Math.max(0, height)}px`;
  }

  function clearTrackedRows() {
    rowsBySymbol.clear();
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    viewport.removeEventListener("scroll", scheduleWindowRender);
    resizeObserver?.disconnect();
    if (!resizeObserver) {
      window.removeEventListener("resize", scheduleWindowRender);
    }
    if (renderFrame) {
      window.cancelAnimationFrame(renderFrame);
      renderFrame = 0;
    }
    clearTrackedRows();
  }

  function createEmptyRow(hasSourceRows) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = COLUMN_COUNT;
    td.className = "empty";
    td.textContent = hasSourceRows ? FILTERED_EMPTY_MESSAGE : LOADING_MESSAGE;
    tr.append(td);
    return tr;
  }

  return {
    dispose,
    render,
    patchRows,
    scrollToTop,
  };
}
