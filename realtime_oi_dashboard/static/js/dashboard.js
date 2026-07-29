import { createFilterBar } from "./components/FilterBar.js";
import { createHighOi7dTable } from "./components/HighOi7dTable.js";
import { createMarketTooltip } from "./components/MarketTooltip.js";
import { createOiRankingTable } from "./components/OiRankingTable.js";
import { createSortableHeaders } from "./components/SortableHeader.js";
import { renderStatCards, renderWsState } from "./components/StatCard.js";
import { createBinancePriceFeed } from "./data/BinancePriceFeed.js";
import { useFavorites } from "./hooks/useFavorites.js";
import { useOiRankingData } from "./hooks/useOiRankingData.js";
import { useTableFilters } from "./hooks/useTableFilters.js";
import { useTableSort } from "./hooks/useTableSort.js";
import { createMotionEffects } from "./motionEffects.js";
import { createOiRefreshController } from "./services/OiRefreshController.js";
import { createRankingProcessor } from "./services/RankingProcessor.js";
import { createUiRenderScheduler } from "./services/UiRenderScheduler.js";

const lifecycleController = new AbortController();
const EMPTY_HEAT_MAX = Object.freeze({
  fundingRatePercent: 0,
  priceChangePercent: 0,
  price7dChangePercent: 0,
  oi24hChangePercent: 0,
  oi7dChangePercent: 0,
});
const PRICE_STATUS_LABELS = Object.freeze({
  connecting: "连接中",
  error: "异常",
  live: "实时",
  paused: "暂停",
  reconnecting: "重连中",
});
const FAVORITE_SEED_SYMBOLS = Object.freeze([
  "AIGENSYNUSDT",
  "XPLUSDT",
  "WLFIUSDT",
  "OPENUSDT",
  "HYPEUSDT",
  "EIGENUSDT",
  "PUMPUSDT",
  "PENDLEUSDT",
  "PENGUUSDT",
  "TIAUSDT",
  "BTWUSDT",
  "MITOUSDT",
  "KAITOUSDT",
  "LUMIAUSDT",
  "LDOUSDT",
  "SAGAUSDT",
  "ENAUSDT",
  "ZROUSDT",
  "AAVEUSDT",
  "ZBTUSDT",
  "ENSOUSDT",
  "FFUSDT",
]);

const elements = {
  statusTitle: document.getElementById("statusTitle"),
  statusText: document.getElementById("statusText"),
  wsState: document.getElementById("wsState"),
  topIncrease: document.getElementById("topIncrease"),
  topIncreaseNote: document.getElementById("topIncreaseNote"),
  topDecrease: document.getElementById("topDecrease"),
  topDecreaseNote: document.getElementById("topDecreaseNote"),
  searchInput: document.getElementById("searchInput"),
  favoritesOnlyBtn: document.getElementById("favoritesOnlyBtn"),
  oiValueFilter: document.getElementById("oiValueFilter"),
  volumeFilter: document.getElementById("volumeFilter"),
  limitSelect: document.getElementById("limitSelect"),
  signalOi7dFilter: document.getElementById("signalOi7dFilter"),
  signalOiValueFilter: document.getElementById("signalOiValueFilter"),
  rankBody: document.getElementById("rankBody"),
  highOi7dBody: document.getElementById("highOi7dBody"),
  sortableHeaders: document.querySelectorAll("th[data-sort]"),
};

const rankingData = useOiRankingData();
const favorites = useFavorites("oiFavorites", {
  removedSeedSymbols: ["METUSDT", "HOLOUSDT"],
  seedSymbols: FAVORITE_SEED_SYMBOLS,
  seedVersion: "watchlist-2026-07-29-v3",
});
const filters = useTableFilters({
  query: elements.searchInput.value.trim().toUpperCase(),
  limit: Number(elements.limitSelect.value),
  minOiValue: Number(elements.oiValueFilter.value),
  minVolume: Number(elements.volumeFilter.value),
});
const sort = useTableSort({ storageKey: "oiTableSort" });
const motionEffects = createMotionEffects();
const priceFeed = createBinancePriceFeed();
const rankingProcessor = createRankingProcessor();

let heatMax = EMPTY_HEAT_MAX;
let visibleRows = [];
let highOi7dRows = [];
let disposed = false;
let latestViewRequest = 0;

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
  sort,
  onChange: resetTableAndRequestView,
  signal: lifecycleController.signal,
});

const uiScheduler = createUiRenderScheduler(flushUiRender);
const scheduleUiRender = uiScheduler.schedule;
const oiRefresh = createOiRefreshController({
  onPayload: handleOiPayload,
  onError: handleOiError,
  onSettled: handleOiSettled,
});

const unsubscribePriceStatus = priceFeed.subscribeStatus(status => {
  if (disposed) return;
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
document.addEventListener("visibilitychange", syncAnimationState);
window.addEventListener("focus", syncAnimationState);
window.addEventListener("blur", syncAnimationState);
window.addEventListener("pagehide", handlePageHide);
window.addEventListener("pageshow", handlePageShow);
syncAnimationState();
startLiveUpdates();
motionEffects.playEntrance();

function dispose() {
  if (disposed) return;
  disposed = true;
  document.removeEventListener("visibilitychange", syncAnimationState);
  window.removeEventListener("focus", syncAnimationState);
  window.removeEventListener("blur", syncAnimationState);
  window.removeEventListener("pagehide", handlePageHide);
  window.removeEventListener("pageshow", handlePageShow);
  lifecycleController.abort();
  unsubscribePriceStatus();
  unsubscribePrices();
  rankingProcessor.dispose();
  marketTooltip.dispose();
  motionEffects.dispose();
  table.dispose();
  stopLiveUpdates();
  oiRefresh.dispose();
  latestViewRequest += 1;
  uiScheduler.dispose();
}

function syncAnimationState() {
  if (disposed) return;
  const backgrounded = document.hidden || !document.hasFocus();
  document.documentElement.classList.toggle("page-hidden", backgrounded);
  motionEffects.setPaused(backgrounded);
  if (!backgrounded && oiRefresh.isRunning()) oiRefresh.refresh();
}

function startLiveUpdates() {
  if (disposed || oiRefresh.isRunning()) return;
  priceFeed.connect();
  oiRefresh.start();
}

function stopLiveUpdates() {
  oiRefresh.stop();
  priceFeed.close();
}

function handlePageHide(event) {
  document.documentElement.classList.add("page-hidden");
  motionEffects.setPaused(true);
  if (event.persisted) {
    stopLiveUpdates();
    return;
  }
  dispose();
}

function handlePageShow(event) {
  if (!event.persisted) return;
  syncAnimationState();
  startLiveUpdates();
}

function handleOiPayload(payload) {
  const favoritesChanged = favorites.pruneInactive(payload.active_symbols);
  rankingData.setRows(payload.rows, priceFeed.getPrices());
  renderOiStatus(payload);
  requestRankingView({
    replaceRows: rankingData.getRows(),
    changedSymbols: rankingData.getRows().map(row => row.symbol),
    forceFull: !visibleRows.length,
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
  elements.statusTitle.textContent = "OI 连接异常";
  elements.statusText.textContent = error.message;
}

function handleOiSettled() {
  scheduleUiRender({
    high: true,
    patchSymbols: visibleRows.map(row => row.symbol),
  });
}

function renderOiStatus(payload) {
  const loadedSymbols = payload.rows.length;
  elements.statusTitle.textContent = payload.error
    ? "OI 更新异常"
    : loadedSymbols ? "实时 OI 变化" : "等待本次 OI 数据";
  const errorCount = payload.recent_errors?.length || 0;
  const errorText = errorCount ? ` · 错误 ${errorCount}` : "";
  const batchError = typeof payload.error === "string" && payload.error
    ? ` · ${payload.error}`
    : "";
  const savedAt = payload.saved_at || "尚无 OI";
  const totalSymbols = payload.total_symbols || 0;
  elements.statusText.textContent = [
    `${savedAt} · 已加载 ${loadedSymbols}/${totalSymbols}`,
    errorText,
    batchError,
  ].join("");
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
  if (disposed) return;
  const affectedSymbols = rankingData.applyPriceUpdates(changedSymbols, priceMap);
  if (!affectedSymbols.length) return;

  requestRankingView({
    patchRows: affectedSymbols
      .map(symbol => rankingData.getRow(symbol))
      .filter(Boolean),
    changedSymbols: affectedSymbols,
  });
}

function requestRankingView({
  replaceRows,
  patchRows = [],
  changedSymbols = [],
  forceFull = false,
  forceHigh = false,
} = {}) {
  const requestVersion = ++latestViewRequest;
  const previousVisibleSymbols = visibleRows.map(row => row.symbol);
  const previousHighSymbols = highOi7dRows.map(row => row.symbol);
  const previousHeatMax = heatMax;

  rankingProcessor.request({
    replaceRows,
    patchRows,
    filters: filters.getState(),
    sort: sort.getState(),
    favorites: favorites.getSet(),
    signalFilters: getSignalFilters(),
  }).then(view => {
    if (disposed || requestVersion !== latestViewRequest) return;

    const nextVisibleRows = rowsForSymbols(view.visibleSymbols);
    const nextHighRows = rowsForSymbols(view.highOi7dSymbols);
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

    scheduleUiRender({
      full: forceFull || visibleOrderChanged || replaceRows !== undefined,
      high: forceFull || forceHigh || highRowsChanged || replaceRows !== undefined
        || patchRows.length > 0,
      patchSymbols: heatChanged ? view.visibleSymbols : changedSymbols,
    });
  }).catch(error => {
    if (disposed) return;
    elements.statusTitle.textContent = "排行计算异常";
    elements.statusText.textContent = error.message;
  });
}

function rowsForSymbols(symbols) {
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

function flushUiRender({
  full,
  high,
  controls,
  stats,
  priceStatus,
  patchSymbols,
}) {
  if (priceStatus) {
    const label = PRICE_STATUS_LABELS[priceStatus] || "连接中";
    motionEffects.pulseValues(renderWsState(elements.wsState, label));
  }

  if (stats) {
    motionEffects.pulseValues(
      renderStatCards(elements, rankingData.getStats()),
    );
  }

  if (full) {
    motionEffects.revealRows(
      table.render(visibleRows, getRowRenderContext()),
    );
  } else if (patchSymbols.size) {
    table.patchRows(patchSymbols, getRowRenderContext());
  }

  if (high) {
    motionEffects.revealRows(
      highOi7dTable.render(
        highOi7dRows,
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
    heatMax,
  };
}
