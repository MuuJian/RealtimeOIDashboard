import { formatCurrency } from "../utils/format.js";
import { syncChildren } from "../utils/dom.js";
import {
  createMarketRowCells,
  updateMarketRowCells,
} from "./MarketRowCells.js";

const LOADING_MESSAGE = "正在获取本次启动后的 OI 数据。";

export function createHighOi7dTable({ tbody }) {
  const rowsBySymbol = new Map();
  const emptyRow = createEmptyRow();

  function render(rows, hasSourceRows, signalFilters) {
    if (!rows.length) {
      rowsBySymbol.clear();
      emptyRow._message.textContent = hasSourceRows
        ? emptyMessage(signalFilters)
        : LOADING_MESSAGE;
      syncChildren(tbody, [emptyRow]);
      return [];
    }

    const nextSymbols = new Set();
    const createdRows = [];
    const nextChildren = [];

    for (const row of rows) {
      nextSymbols.add(row.symbol);

      let tr = rowsBySymbol.get(row.symbol);
      if (!tr) {
        tr = createRow();
        rowsBySymbol.set(row.symbol, tr);
        createdRows.push(tr);
      }
      updateRow(tr, row);
      nextChildren.push(tr);
    }

    for (const [symbol, tr] of rowsBySymbol.entries()) {
      if (!nextSymbols.has(symbol)) {
        tr.remove();
        rowsBySymbol.delete(symbol);
      }
    }

    syncChildren(tbody, nextChildren);
    return createdRows;
  }

  function createRow() {
    const tr = document.createElement("tr");
    tr._marketCells = createMarketRowCells();
    tr.append(...tr._marketCells.orderedCells);
    return tr;
  }

  function updateRow(tr, row) {
    tr.dataset.symbol = row.symbol;
    updateMarketRowCells(tr._marketCells, row);
  }

  function createEmptyRow() {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 10;
    td.className = "empty";
    tr.append(td);
    tr._message = td;
    return tr;
  }

  return { render };
}

function emptyMessage(signalFilters) {
  const oiThreshold = Number(signalFilters?.minOi7dChangePercent ?? 100);
  const valueThreshold = Number(signalFilters?.minOiValue ?? 10000000);
  const formattedValue = formatCurrency(valueThreshold).replace(".00", "");
  return `暂无满足 7D 持仓 > ${oiThreshold}% 且持仓价值 > ${formattedValue} 的币种。`;
}
