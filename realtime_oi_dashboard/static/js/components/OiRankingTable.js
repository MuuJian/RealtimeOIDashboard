import { createRankingRow, updateRankingRow } from "./OiRankingRow.js";

const LOADING_MESSAGE =
  "正在获取本次启动后的 OI 数据，结果会按批次逐步出现。";
const FILTERED_EMPTY_MESSAGE = "暂无符合当前筛选条件的币种。";

export function createOiRankingTable({ tbody, getRowBySymbol }) {
  const rowsBySymbol = new Map();
  const visibleSymbols = new Set();

  function render(rows, context) {
    visibleSymbols.clear();

    if (!rows.length) {
      rowsBySymbol.clear();
      tbody.textContent = "";
      tbody.append(createEmptyRow(context.hasSourceRows));
      return [];
    }

    const fragment = document.createDocumentFragment();
    const nextVisible = new Set();
    const createdRows = [];

    for (const row of rows) {
      nextVisible.add(row.symbol);
      visibleSymbols.add(row.symbol);

      let tr = rowsBySymbol.get(row.symbol);
      if (!tr) {
        tr = createRankingRow(row, context);
        rowsBySymbol.set(row.symbol, tr);
        createdRows.push(tr);
      } else {
        updateRankingRow(tr, row, context);
      }
      fragment.append(tr);
    }

    for (const [symbol, tr] of rowsBySymbol.entries()) {
      if (!nextVisible.has(symbol)) {
        tr.remove();
        rowsBySymbol.delete(symbol);
      }
    }

    tbody.textContent = "";
    tbody.append(fragment);
    return createdRows;
  }

  function patchRows(symbols, context) {
    for (const symbol of symbols) {
      if (!visibleSymbols.has(symbol)) continue;

      const tr = rowsBySymbol.get(symbol);
      const row = getRowBySymbol(symbol);
      if (tr && row) updateRankingRow(tr, row, context);
    }
  }

  function createEmptyRow(hasSourceRows) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 10;
    td.className = "empty";
    td.textContent = hasSourceRows ? FILTERED_EMPTY_MESSAGE : LOADING_MESSAGE;
    tr.append(td);
    return tr;
  }

  return {
    render,
    patchRows,
  };
}
