const EMPTY_HEAT_MAX = Object.freeze({
  fundingRatePercent: 0,
  priceChangePercent: 0,
  price7dChangePercent: 0,
  oi24hChangePercent: 0,
  oi7dChangePercent: 0,
});

export function createRankingViewController({
  processor,
  rankingData,
  filters,
  sort,
  favorites,
  getSignalFilters,
  scheduleRender,
  onError,
}) {
  let heatMax = EMPTY_HEAT_MAX;
  let visibleRows = [];
  let highOi7dRows = [];
  let disposed = false;
  let latestRequest = 0;

  function request({
    replaceRows,
    patchRows = [],
    changedSymbols = [],
    forceFull = false,
    forceHigh = false,
  } = {}) {
    const requestVersion = ++latestRequest;
    const previousVisibleSymbols = visibleRows.map(row => row.symbol);
    const previousHighSymbols = highOi7dRows.map(row => row.symbol);
    const previousHeatMax = heatMax;

    processor.request({
      replaceRows,
      patchRows,
      filters: filters.getState(),
      sort: sort.getState(),
      favorites: favorites.getSet(),
      signalFilters: getSignalFilters(),
    }).then(view => {
      if (disposed || requestVersion !== latestRequest) return;

      const nextVisibleRows = rowsForSymbols(view.visibleSymbols, rankingData);
      const nextHighRows = rowsForSymbols(view.highOi7dSymbols, rankingData);
      const visibleOrderChanged = !sameSymbols(
        previousVisibleSymbols,
        view.visibleSymbols,
      );
      const highRowsChanged = !sameSymbols(
        previousHighSymbols,
        view.highOi7dSymbols,
      );
      const heatChanged = !sameHeatMax(previousHeatMax, view.heatMax);

      visibleRows = nextVisibleRows;
      highOi7dRows = nextHighRows;
      heatMax = view.heatMax;

      scheduleRender({
        full: forceFull || visibleOrderChanged || replaceRows !== undefined,
        high: forceFull || forceHigh || highRowsChanged
          || replaceRows !== undefined || patchRows.length > 0,
        patchSymbols: heatChanged ? view.visibleSymbols : changedSymbols,
      });
    }).catch(error => {
      if (!disposed) onError(error);
    });
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    latestRequest += 1;
    processor.dispose();
  }

  return {
    dispose,
    getHeatMax: () => heatMax,
    getHighOi7dRows: () => highOi7dRows,
    getVisibleRows: () => visibleRows,
    request,
  };
}

function rowsForSymbols(symbols, rankingData) {
  const rows = [];
  for (const symbol of symbols) {
    const row = rankingData.getRow(symbol);
    if (row) rows.push(row);
  }
  return rows;
}

function sameSymbols(previous, next) {
  if (previous.length !== next.length) return false;
  return previous.every((symbol, index) => symbol === next[index]);
}

function sameHeatMax(previous, next) {
  return Object.keys(EMPTY_HEAT_MAX).every(
    key => previous[key] === next[key],
  );
}
