import { createFilterBar } from "./components/FilterBar.js";
import { createHighOi7dTable } from "./components/HighOi7dTable.js";
import { createOiRankingTable } from "./components/OiRankingTable.js";
import { createSortableHeaders } from "./components/SortableHeader.js";
import { renderStatCards, renderWsState } from "./components/StatCard.js";
import { createBinancePriceFeed } from "./data/BinancePriceFeed.js";
import { useFavorites } from "./hooks/useFavorites.js";
import { loadOiSnapshot, useOiRankingData } from "./hooks/useOiRankingData.js";
import { useTableFilters } from "./hooks/useTableFilters.js";
import { useTableSort } from "./hooks/useTableSort.js";
import { createMotionEffects } from "./motionEffects.js";
import { createParticleField } from "./particleField.js";
import { createRankingProcessor } from "./services/RankingProcessor.js";

const OI_ROWS_MAX_STALE_MS = 15 * 60 * 1000;
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
  rankBody: document.getElementById("rankBody"),
  highOi7dBody: document.getElementById("highOi7dBody"),
  sortableHeaders: document.querySelectorAll("th[data-sort]"),
};

const rankingData = useOiRankingData();
const favorites = useFavorites("oiFavorites");
const filters = useTableFilters({
  query: elements.searchInput.value.trim().toUpperCase(),
  limit: Number(elements.limitSelect.value),
  minOiValue: Number(elements.oiValueFilter.value),
  minVolume: Number(elements.volumeFilter.value),
});
const sort = useTableSort();
const motionEffects = createMotionEffects();
const particleField = createParticleField(
  document.getElementById("particleField"),
);
const priceFeed = createBinancePriceFeed();
const rankingProcessor = createRankingProcessor();

let heatMax = EMPTY_HEAT_MAX;
let visibleRows = [];
let highOi7dRows = [];
let uiFrame = 0;
let refreshTimer = null;
let oiRefreshInFlight = false;
let lastOiResponseAt = null;
let disposed = false;
let latestViewRequest = 0;
let pendingFullRender = false;
let pendingHighRender = false;
let pendingControlsRender = false;
let pendingStatsRender = false;
let pendingPriceStatus = null;
let pendingPatchSymbols = new Set();

const table = createOiRankingTable({
  tbody: elements.rankBody,
  getRowBySymbol: rankingData.getRow,
});

const highOi7dTable = createHighOi7dTable({
  tbody: elements.highOi7dBody,
});

const filterBar = createFilterBar({
  elements,
  filters,
  favorites,
  onChange: resetTableAndRequestView,
});

const sortableHeaders = createSortableHeaders({
  headers: elements.sortableHeaders,
  sort,
  onChange: resetTableAndRequestView,
});

const unsubscribePriceStatus = priceFeed.subscribeStatus(status => {
  if (disposed) return;
  scheduleUiRender({ priceStatus: status });
});
const unsubscribePrices = priceFeed.subscribePrices(handlePriceBatch);

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
});

scheduleUiRender({
  controls: true,
  full: true,
  high: true,
});
document.addEventListener("visibilitychange", syncLiveUpdates);
window.addEventListener("pagehide", handlePageHide);
window.addEventListener("pageshow", handlePageShow);
syncLiveUpdates();
motionEffects.playEntrance();

function dispose() {
  if (disposed) return;
  disposed = true;
  document.removeEventListener("visibilitychange", syncLiveUpdates);
  window.removeEventListener("pagehide", handlePageHide);
  window.removeEventListener("pageshow", handlePageShow);
  lifecycleController.abort();
  unsubscribePriceStatus();
  unsubscribePrices();
  rankingProcessor.dispose();
  motionEffects.dispose();
  particleField.dispose();
  table.dispose();
  stopLiveUpdates();
  cancelScheduledRenders();
}

function syncLiveUpdates() {
  if (disposed) return;
  if (document.hidden) {
    stopLiveUpdates();
    return;
  }

  startLiveUpdates();
}

function startLiveUpdates() {
  if (disposed || document.hidden || refreshTimer !== null) return;
  priceFeed.connect();
  refreshOi();
  refreshTimer = window.setInterval(refreshOi, 10000);
}

function stopLiveUpdates() {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  priceFeed.close();
}

function handlePageHide(event) {
  if (event.persisted) {
    stopLiveUpdates();
    return;
  }
  dispose();
}

function handlePageShow(event) {
  if (event.persisted) syncLiveUpdates();
}

async function refreshOi() {
  if (oiRefreshInFlight || disposed) return;
  oiRefreshInFlight = true;
  try {
    const payload = await loadOiSnapshot({ signal: lifecycleController.signal });
    if (disposed) return;
    lastOiResponseAt = responseClock();
    rankingData.setRows(payload.rows, priceFeed.getPrices());
    renderOiStatus(payload);
    requestRankingView({
      replaceRows: rankingData.getRows(),
      changedSymbols: rankingData.getRows().map(row => row.symbol),
      forceFull: !visibleRows.length,
    });
    scheduleUiRender({ stats: true });
  } catch (error) {
    if (disposed) return;
    if (lastOiResponseAt && isResponseStale(lastOiResponseAt)) {
      lastOiResponseAt = null;
      rankingData.setRows([], priceFeed.getPrices());
      requestRankingView({
        replaceRows: [],
        forceFull: true,
      });
      scheduleUiRender({ stats: true });
    }
    elements.statusTitle.textContent = "OI 连接异常";
    elements.statusText.textContent = error.message;
  } finally {
    oiRefreshInFlight = false;
  }
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
      high: forceFull || highRowsChanged || replaceRows !== undefined
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

function scheduleUiRender({
  full = false,
  high = false,
  controls = false,
  stats = false,
  priceStatus,
  patchSymbols = [],
} = {}) {
  if (full) {
    pendingFullRender = true;
    pendingPatchSymbols.clear();
  } else if (!pendingFullRender) {
    for (const symbol of patchSymbols) pendingPatchSymbols.add(symbol);
  }
  pendingHighRender ||= high;
  pendingControlsRender ||= controls;
  pendingStatsRender ||= stats;
  if (priceStatus) pendingPriceStatus = priceStatus;

  if (uiFrame) return;
  uiFrame = window.requestAnimationFrame(flushUiRender);
}

function flushUiRender() {
  uiFrame = 0;

  if (pendingPriceStatus) {
    const label = PRICE_STATUS_LABELS[pendingPriceStatus] || "连接中";
    motionEffects.pulseValues(renderWsState(elements.wsState, label));
    pendingPriceStatus = null;
  }

  if (pendingStatsRender) {
    motionEffects.pulseValues(
      renderStatCards(elements, rankingData.getStats()),
    );
    pendingStatsRender = false;
  }

  if (pendingFullRender) {
    motionEffects.revealRows(
      table.render(visibleRows, getRowRenderContext()),
    );
    pendingFullRender = false;
    pendingPatchSymbols.clear();
  } else if (pendingPatchSymbols.size) {
    table.patchRows(pendingPatchSymbols, getRowRenderContext());
    pendingPatchSymbols.clear();
  }

  if (pendingHighRender) {
    motionEffects.revealRows(
      highOi7dTable.render(
        highOi7dRows,
        rankingData.getRows().length > 0,
      ),
    );
    pendingHighRender = false;
  }

  if (pendingControlsRender) {
    filterBar.render();
    sortableHeaders.render();
    pendingControlsRender = false;
  }
}

function getRowRenderContext() {
  return {
    favorites: favorites.getSet(),
    hasSourceRows: rankingData.getRows().length > 0,
    heatMax,
  };
}

function cancelScheduledRenders() {
  latestViewRequest += 1;
  if (uiFrame) {
    window.cancelAnimationFrame(uiFrame);
    uiFrame = 0;
  }
  pendingFullRender = false;
  pendingHighRender = false;
  pendingControlsRender = false;
  pendingStatsRender = false;
  pendingPriceStatus = null;
  pendingPatchSymbols.clear();
}

function responseClock() {
  return {
    wall: Date.now(),
    monotonic: performance.now(),
  };
}

function isResponseStale(previous) {
  return Date.now() - previous.wall > OI_ROWS_MAX_STALE_MS
    || performance.now() - previous.monotonic > OI_ROWS_MAX_STALE_MS;
}
