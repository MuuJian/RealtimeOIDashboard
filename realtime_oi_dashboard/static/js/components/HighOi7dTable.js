import {
  binanceFuturesUrl,
  formatCurrency,
  formatFundingTitle,
  formatFundingRate,
  formatPercent,
  formatPrice,
  signClass,
  tradingViewUrl,
} from "../utils/format.js";
import { syncChildren } from "../utils/dom.js";

const EMPTY_MESSAGE = "暂无满足 7D 持仓 > 100% 且持仓价值 > $1000万 的币种。";
const LOADING_MESSAGE = "正在获取本次启动后的 OI 数据。";

export function createHighOi7dTable({ tbody }) {
  const rowsBySymbol = new Map();
  const emptyRow = createEmptyRow();

  function render(rows, hasSourceRows) {
    if (!rows.length) {
      rowsBySymbol.clear();
      emptyRow._message.textContent = hasSourceRows
        ? EMPTY_MESSAGE
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
    const symbolCell = document.createElement("td");
    symbolCell.className = "symbol";
    const symbolLink = createLink();
    symbolCell.append(symbolLink);

    const priceCell = document.createElement("td");
    const priceLink = createLink();
    priceCell.append(priceLink);

    const fundingRateCell = document.createElement("td");
    const changeCell = document.createElement("td");
    changeCell.className = "heat";
    const valueCell = document.createElement("td");

    tr.append(symbolCell, fundingRateCell, priceCell, changeCell, valueCell);
    tr._cells = { symbolLink, priceLink, fundingRateCell, changeCell, valueCell };
    return tr;
  }

  function updateRow(tr, row) {
    const cells = tr._cells;
    cells.symbolLink.href = binanceFuturesUrl(row.symbol);
    cells.symbolLink.textContent = row.symbol;
    cells.priceLink.href = tradingViewUrl(row.symbol);
    cells.priceLink.textContent = formatPrice(row.price);
    cells.fundingRateCell.className = `heat ${signClass(row.fundingRatePercent)}`;
    cells.fundingRateCell.title = formatFundingTitle(row.nextFundingTime);
    cells.fundingRateCell.textContent = formatFundingRate(row.fundingRatePercent);
    cells.changeCell.className = `heat ${signClass(row.oi7dChangePercent)}`;
    cells.changeCell.textContent = formatPercent(row.oi7dChangePercent);
    cells.valueCell.textContent = formatCurrency(row.currentOiValue);
  }

  function createEmptyRow() {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "empty";
    tr.append(td);
    tr._message = td;
    return tr;
  }

  function createLink() {
    const link = document.createElement("a");
    link.className = "symbol-link";
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  }

  return { render };
}
