import { createOiRefreshController } from "./OiRefreshController.js";

export function createOiFeatureController({
  dashboardStatus,
  favorites,
  isDisposed,
  priceFeed,
  rankingData,
  rankingView,
  requestRankingView,
  scheduleUiRender,
}) {
  const refresh = createOiRefreshController({
    onPayload: handlePayload,
    onError: handleError,
    onSettled: handleSettled,
  });
  const unsubscribeStatus = priceFeed.subscribeStatus(status => {
    if (!isDisposed()) scheduleUiRender({ priceStatus: status });
  });
  const unsubscribePrices = priceFeed.subscribePrices(handlePriceBatch);

  function handlePayload(payload) {
    const favoritesChanged = favorites.pruneInactive(payload.active_symbols);
    rankingData.setRows(payload.rows, priceFeed.getPrices());
    dashboardStatus.renderPayload(payload);
    requestRankingView({
      replaceRows: rankingData.getRows(),
      changedSymbols: rankingData.getRows().map(row => row.symbol),
      forceFull: !rankingView.getVisibleRows().length,
    });
    scheduleUiRender({ controls: favoritesChanged, stats: true });
  }

  function handleError(error, { dataExpired }) {
    if (dataExpired) {
      rankingData.setRows([], priceFeed.getPrices());
      requestRankingView({ replaceRows: [], forceFull: true });
      scheduleUiRender({ stats: true });
    }
    dashboardStatus.renderConnectionError(error);
  }

  function handleSettled() {
    scheduleUiRender({
      high: true,
      patchSymbols: rankingView.getVisibleRows().map(row => row.symbol),
    });
  }

  function handlePriceBatch(changedSymbols, priceMap) {
    if (isDisposed()) return;
    const affectedSymbols = rankingData.applyPriceUpdates(
      changedSymbols,
      priceMap,
    );
    if (!affectedSymbols.length) return;

    scheduleUiRender({ stats: true });
    requestRankingView({
      patchRows: affectedSymbols
        .map(symbol => rankingData.getRow(symbol))
        .filter(Boolean),
      changedSymbols: affectedSymbols,
    });
  }

  return {
    dispose() {
      unsubscribeStatus();
      unsubscribePrices();
    },
    refresh,
  };
}
