import {
  applyLivePriceToRow,
  syncOiToMarketCapRatio,
} from "../../utils/rankingRows.js";
import { buildOiStats } from "../../utils/oiStats.js";
import { isOiRow } from "./OiPayloadSchema.js";

const LIVE_MARKET_FIELDS = [
  "price",
  "volume24h",
  "priceChangePercent",
  "price7dChangePercent",
  "currentOiValue",
];

export function createOiRankingStore() {
  const serverRowsBySymbol = new Map();
  const rowsBySymbol = new Map();
  let rows = [];
  let stats = buildOiStats(rows);

  function setRows(nextRows, priceMap) {
    const seen = new Set();

    for (const item of nextRows) {
      if (!isOiRow(item)) continue;

      const serverRow = { ...item };
      const row = { ...serverRow };
      applyLivePriceToRow(row, priceMap.get(item.symbol));
      serverRowsBySymbol.set(item.symbol, serverRow);
      rowsBySymbol.set(item.symbol, row);
      seen.add(item.symbol);
    }

    for (const symbol of rowsBySymbol.keys()) {
      if (seen.has(symbol)) continue;
      serverRowsBySymbol.delete(symbol);
      rowsBySymbol.delete(symbol);
    }

    rows = [...rowsBySymbol.values()];
    stats = buildOiStats(rows);
  }

  function applyPriceUpdates(symbols, priceMap) {
    const affectedSymbols = [];

    for (const symbol of symbols) {
      const row = rowsBySymbol.get(symbol);
      const serverRow = serverRowsBySymbol.get(symbol);
      if (!row || !serverRow) continue;

      const livePrice = priceMap.get(symbol);
      const changed = livePrice
        ? applyLivePriceToRow(row, livePrice)
        : restoreServerMarketData(row, serverRow);
      if (changed) affectedSymbols.push(symbol);
    }

    return affectedSymbols;
  }

  return {
    setRows,
    applyPriceUpdates,
    getRows() {
      return rows;
    },
    getRow(symbol) {
      return rowsBySymbol.get(symbol);
    },
    getStats() {
      return stats;
    },
  };
}

function restoreServerMarketData(row, serverRow) {
  let changed = false;
  for (const field of LIVE_MARKET_FIELDS) {
    if (row[field] === serverRow[field]) continue;
    row[field] = serverRow[field];
    changed = true;
  }
  return syncOiToMarketCapRatio(row) || changed;
}
