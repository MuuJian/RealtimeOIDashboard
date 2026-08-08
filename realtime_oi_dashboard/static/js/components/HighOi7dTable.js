import { formatCurrency } from "../utils/format.js";
import { syncChildren } from "../utils/dom.js";
import {
  createMarketRowCells,
  updateMarketRowCells,
} from "./MarketRowCells.js";

const LOADING_MESSAGE = "正在獲取本次啟動後的 OI 數據。";

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
    tr._marketCells = createMarketRowCells({
      includeMarketCap: true,
      oiChangesBeforeValue: true,
    });
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
    td.colSpan = 11;
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
  return `暫無滿足 7D 持倉 > ${oiThreshold}% 且持倉價值 > ${formattedValue} 的幣種。`;
}
