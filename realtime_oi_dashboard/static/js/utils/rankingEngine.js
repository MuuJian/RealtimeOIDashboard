import {
  buildHighOi7dRows,
  buildVisibleRows,
  getHeatMax,
} from "./rankingRows.js";

export function computeRankingView(
  rows,
  filters,
  sortState,
  favorites,
  signalFilters,
) {
  const visibleRows = buildVisibleRows(rows, filters, sortState, favorites);
  return {
    visibleSymbols: visibleRows.map(row => row.symbol),
    highOi7dSymbols: buildHighOi7dRows(rows, signalFilters)
      .map(row => row.symbol),
    heatMax: getHeatMax(visibleRows),
  };
}
