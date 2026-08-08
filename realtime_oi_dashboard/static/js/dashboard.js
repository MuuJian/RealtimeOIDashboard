import { createFilterBar } from "./components/FilterBar.js";
import { createDashboardStatus } from "./components/DashboardStatus.js";
import { createHighOi7dTable } from "./components/HighOi7dTable.js";
import { createMarketTooltip } from "./components/MarketTooltip.js";
import { createOiRankingTable } from "./components/OiRankingTable.js";
import { createSortableHeaders } from "./components/SortableHeader.js";
import { createBinancePriceFeed } from "./data/BinancePriceFeed.js";
import { getDashboardElements } from "./data/DashboardElements.js";
import { createOiRankingStore } from "./data/OiRankingStore.js";
import { useFavorites } from "./hooks/useFavorites.js";
import { useTableFilters } from "./hooks/useTableFilters.js";
import { useTableSort } from "./hooks/useTableSort.js";
import { createMotionEffects } from "./motionEffects.js";
import { createOiRefreshController } from "./services/OiRefreshController.js";
import { createPageLifecycle } from "./services/PageLifecycle.js";
import { createDashboardRenderer } from "./services/DashboardRenderer.js";
import { createRankingProcessor } from "./services/RankingProcessor.js";
import { createRankingViewController } from "./services/RankingViewController.js";
import { createUiRenderScheduler } from "./services/UiRenderScheduler.js";

const lifecycleController = new AbortController();
const elements = getDashboardElements();
const dashboardStatus = createDashboardStatus({
  title: elements.statusTitle,
  detail: elements.statusText,
  oiLoaded: elements.oiLoadedText,
  marketCapLoaded: elements.marketCapLoadedText,
});

const rankingData = createOiRankingStore();
const favorites = useFavorites("oiFavorites");
const filters = useTableFilters({
  query: elements.searchInput.value.trim().toUpperCase(),
  limit: Number(elements.limitSelect.value),
  minOiValue: Number(elements.oiValueFilter.value),
  minVolume: Number(elements.volumeFilter.value),
});
const sort = useTableSort({ storageKey: "oiTableSortV2" });
const motionEffects = createMotionEffects();
const priceFeed = createBinancePriceFeed();
const rankingProcessor = createRankingProcessor();

const table = createOiRankingTable({
  tbody: elements.rankBody,
  getRowBySymbol: rankingData.getRow,
});

const highOi7dTable = createHighOi7dTable({
  tbody: elements.highOi7dBody,
});

const marketTooltip = createMarketTooltip({
  containers: [elements.rankBody, elements.highOi7dBody],
  getRowBySymbol: rankingData.getRow,
});

const filterBar = createFilterBar({
  elements,
  filters,
  onChange: resetTableAndRequestView,
  signal: lifecycleController.signal,
});

const sortableHeaders = createSortableHeaders({
  headers: elements.sortableHeaders,
  select: elements.sortSelect,
  sort,
  onChange: resetTableAndRequestView,
  signal: lifecycleController.signal,
});

const dashboardRenderer = createDashboardRenderer({
  elements,
  motionEffects,
  rankingData,
  favorites,
  table,
  highOi7dTable,
  filterBar,
  sortableHeaders,
  getVisibleRows: () => rankingView.getVisibleRows(),
  getHighOi7dRows: () => rankingView.getHighOi7dRows(),
  getHeatMax: () => rankingView.getHeatMax(),
  getSignalFilters,
});
const uiScheduler = createUiRenderScheduler(dashboardRenderer.render);
const scheduleUiRender = uiScheduler.schedule;
const rankingView = createRankingViewController({
  processor: rankingProcessor,
  rankingData,
  filters,
  sort,
  favorites,
  getSignalFilters,
  scheduleRender: scheduleUiRender,
  onError: handleRankingError,
});
const oiRefresh = createOiRefreshController({
  onPayload: handleOiPayload,
  onError: handleOiError,
  onSettled: handleOiSettled,
});
const pageLifecycle = createPageLifecycle({
  onBackgroundChange: setBackgrounded,
  onForeground: refreshAfterForeground,
  onStart: startLiveUpdates,
  onStop: stopLiveUpdates,
  onDispose: disposeResources,
});

const unsubscribePriceStatus = priceFeed.subscribeStatus(status => {
  if (pageLifecycle.isDisposed()) return;
  scheduleUiRender({ priceStatus: status });
});
const unsubscribePrices = priceFeed.subscribePrices(handlePriceBatch);

for (const select of [
  elements.signalOi7dFilter,
  elements.signalOiValueFilter,
]) {
  select.addEventListener("change", handleSignalFilterChange, {
    signal: lifecycleController.signal,
  });
}
elements.rankBody.addEventListener("click", event => {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest("[data-favorite]");
  if (!button) return;

  const symbol = button.dataset.favorite;
  favorites.toggle(symbol);
  motionEffects.popFavorite(button);

  if (filters.getState().favoritesOnly) {
    table.scrollToTop();
    requestRankingView({ forceFull: true });
  } else {
    scheduleUiRender({
      controls: true,
      patchSymbols: [symbol],
    });
  }
}, { signal: lifecycleController.signal });

scheduleUiRender({
  controls: true,
  full: true,
  high: true,
});
pageLifecycle.start();
motionEffects.playEntrance();

function disposeResources() {
  lifecycleController.abort();
  unsubscribePriceStatus();
  unsubscribePrices();
  rankingView.dispose();
  marketTooltip.dispose();
  motionEffects.dispose();
  table.dispose();
  dashboardStatus.dispose();
  stopLiveUpdates();
  oiRefresh.dispose();
  uiScheduler.dispose();
}

function setBackgrounded(backgrounded) {
  document.documentElement.classList.toggle("page-hidden", backgrounded);
  motionEffects.setPaused(backgrounded);
}

function refreshAfterForeground() {
  if (oiRefresh.isRunning()) oiRefresh.refresh();
}

function startLiveUpdates() {
  if (oiRefresh.isRunning()) return;
  priceFeed.connect();
  oiRefresh.start();
}

function stopLiveUpdates() {
  oiRefresh.stop();
  priceFeed.close();
}

function handleOiPayload(payload) {
  const favoritesChanged = favorites.pruneInactive(payload.active_symbols);
  rankingData.setRows(payload.rows, priceFeed.getPrices());
  dashboardStatus.renderPayload(payload);
  requestRankingView({
    replaceRows: rankingData.getRows(),
    changedSymbols: rankingData.getRows().map(row => row.symbol),
    forceFull: !rankingView.getVisibleRows().length,
  });
  scheduleUiRender({
    controls: favoritesChanged,
    stats: true,
  });
}

function handleOiError(error, { dataExpired }) {
  if (dataExpired) {
    rankingData.setRows([], priceFeed.getPrices());
    requestRankingView({
      replaceRows: [],
      forceFull: true,
    });
    scheduleUiRender({ stats: true });
  }
  dashboardStatus.renderConnectionError(error);
}

function handleOiSettled() {
  scheduleUiRender({
    high: true,
    patchSymbols: rankingView.getVisibleRows().map(row => row.symbol),
  });
}

function resetTableAndRequestView() {
  table.scrollToTop();
  scheduleUiRender({ controls: true });
  requestRankingView({ forceFull: true });
}

function handleSignalFilterChange() {
  requestRankingView({ forceHigh: true });
}

function getSignalFilters() {
  return {
    minOi7dChangePercent: Number(elements.signalOi7dFilter.value),
    minOiValue: Number(elements.signalOiValueFilter.value),
  };
}

function handlePriceBatch(changedSymbols, priceMap) {
  if (pageLifecycle.isDisposed()) return;
  const affectedSymbols = rankingData.applyPriceUpdates(changedSymbols, priceMap);
  if (!affectedSymbols.length) return;

  scheduleUiRender({ stats: true });
  requestRankingView({
    patchRows: affectedSymbols
      .map(symbol => rankingData.getRow(symbol))
      .filter(Boolean),
    changedSymbols: affectedSymbols,
  });
}

function requestRankingView(options) {
  rankingView.request(options);
}

function handleRankingError(error) {
  if (pageLifecycle.isDisposed()) return;
  dashboardStatus.renderRankingError(error);
}
