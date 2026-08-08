import { renderStatCards, renderWsState } from "../components/StatCard.js";

const PRICE_STATUS_LABELS = Object.freeze({
  connecting: "連接中",
  error: "異常",
  live: "實時",
  paused: "暫停",
  reconnecting: "重連中",
});

export function createDashboardRenderer({
  elements,
  motionEffects,
  rankingData,
  favorites,
  table,
  highOi7dTable,
  filterBar,
  sortableHeaders,
  getVisibleRows,
  getHighOi7dRows,
  getHeatMax,
  getSignalFilters,
}) {
  function render({
    full,
    high,
    controls,
    stats,
    priceStatus,
    patchSymbols,
  }) {
    if (priceStatus) {
      const label = PRICE_STATUS_LABELS[priceStatus] || "連接中";
      motionEffects.pulseValues(renderWsState(elements.wsState, label));
    }

    if (stats) {
      motionEffects.pulseValues(
        renderStatCards(elements, rankingData.getStats()),
      );
    }

    if (full) {
      motionEffects.revealRows(
        table.render(getVisibleRows(), getRowRenderContext()),
      );
    } else if (patchSymbols.size) {
      table.patchRows(patchSymbols, getRowRenderContext());
    }

    if (high) {
      motionEffects.revealRows(
        highOi7dTable.render(
          getHighOi7dRows(),
          rankingData.getRows().length > 0,
          getSignalFilters(),
        ),
      );
    }

    if (controls) {
      filterBar.render();
      sortableHeaders.render();
    }
  }

  function getRowRenderContext() {
    return {
      favorites: favorites.getSet(),
      hasSourceRows: rankingData.getRows().length > 0,
      heatMax: getHeatMax(),
    };
  }

  return { render };
}
