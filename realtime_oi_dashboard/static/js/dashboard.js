import { createFilterBar } from "./components/FilterBar.js";
import { createHighOi7dTable } from "./components/HighOi7dTable.js";
import { createOiRankingTable } from "./components/OiRankingTable.js";
import { createSortableHeaders } from "./components/SortableHeader.js";
import { renderStatCards, renderWsState } from "./components/StatCard.js";
import { useBinancePriceSocket } from "./hooks/useBinancePriceSocket.js";
import { useFavorites } from "./hooks/useFavorites.js";
import { loadOiSnapshot, useOiRankingData } from "./hooks/useOiRankingData.js";
import { useTableFilters } from "./hooks/useTableFilters.js";
import { useTableSort } from "./hooks/useTableSort.js";
import { createMotionEffects } from "./motionEffects.js";
import { createParticleField } from "./particleField.js";
import {
  buildHighOi7dRows,
  buildVisibleRows,
  getHeatMax,
  isPriceDrivenView,
} from "./utils/rankingRows.js";

const OI_ROWS_MAX_STALE_MS = 15 * 60 * 1000;
const lifecycleController = new AbortController();

const elements = {
  statusTitle: document.getElementById("statusTitle"),
  statusText: document.getElementById("statusText"),
  changeCount: document.getElementById("changeCount"),
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

let heatMax = getHeatMax([]);
let fullRenderFrame = 0;
let patchFrame = 0;
let highOi7dFrame = 0;
let refreshTimer = null;
let oiRefreshInFlight = false;
let lastOiResponseAt = null;
let disposed = false;
let pendingPatchSymbols = new Set();
let visibleRowsCache = {
  deps: "",
  rows: [],
};

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
  onChange: scheduleFullRender,
});

const sortableHeaders = createSortableHeaders({
  headers: elements.sortableHeaders,
  sort,
  onChange: scheduleFullRender,
});

const priceSocket = useBinancePriceSocket({
  onStatusChange(value) {
    if (disposed) return;
    motionEffects.pulseValues(renderWsState(elements.wsState, value));
  },
  onPricesChange(changedSymbols, priceMap) {
    if (disposed) return;
    const affectedSymbols = rankingData.applyPriceUpdates(changedSymbols, priceMap);
    if (!affectedSymbols.length) return;

    if (isPriceDrivenView(filters.getState(), sort.getState())) {
      scheduleFullRender();
      return;
    }

    if (fullRenderFrame) return;

    const symbolsToPatch = syncLivePriceHeatScale()
      ? visibleRowsCache.rows.map(row => row.symbol)
      : affectedSymbols;
    scheduleRowPatch(symbolsToPatch);
    scheduleHighOi7dRender();
  },
});

elements.rankBody.addEventListener("click", event => {
  const target = event.target instanceof Element ? event.target : null;
  const button = target?.closest("[data-favorite]");
  if (!button) return;

  const symbol = button.dataset.favorite;
  favorites.toggle(symbol);
  motionEffects.popFavorite(button);
  filterBar.render();

  if (filters.getState().favoritesOnly) {
    scheduleFullRender();
  } else {
    scheduleRowPatch([symbol]);
  }
});

filterBar.render();
sortableHeaders.render();
scheduleFullRender();
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
  motionEffects.dispose();
  particleField.dispose();
  stopLiveUpdates();
  cancelScheduledRenders();
}

function syncLiveUpdates() {
  if (disposed) return;
  if (document.hidden) {
    stopLiveUpdates();
    renderWsState(elements.wsState, "暂停");
    return;
  }

  startLiveUpdates();
}

function startLiveUpdates() {
  if (disposed || document.hidden || refreshTimer !== null) return;
  priceSocket.connect();
  refreshOi();
  refreshTimer = window.setInterval(refreshOi, 10000);
}

function stopLiveUpdates() {
  if (refreshTimer !== null) {
    window.clearInterval(refreshTimer);
    refreshTimer = null;
  }
  priceSocket.close();
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
    rankingData.setRows(payload.rows, priceSocket.getPrices());
    renderOiStatus(payload);
    motionEffects.pulseValues(renderStatCards(elements, rankingData.getStats()));
    scheduleFullRender();
  } catch (error) {
    if (disposed) return;
    if (lastOiResponseAt && isResponseStale(lastOiResponseAt)) {
      lastOiResponseAt = null;
      rankingData.setRows([], priceSocket.getPrices());
      motionEffects.pulseValues(renderStatCards(elements, rankingData.getStats()));
      scheduleFullRender();
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

function scheduleFullRender() {
  if (fullRenderFrame) return;
  fullRenderFrame = window.requestAnimationFrame(renderFull);
}

function scheduleRowPatch(symbols) {
  if (fullRenderFrame) return;

  for (const symbol of symbols) {
    pendingPatchSymbols.add(symbol);
  }

  if (patchFrame) return;
  patchFrame = window.requestAnimationFrame(() => {
    patchFrame = 0;
    const symbolsToPatch = new Set(pendingPatchSymbols);
    pendingPatchSymbols.clear();
    table.patchRows(symbolsToPatch, getRowRenderContext());
  });
}

function renderFull() {
  fullRenderFrame = 0;
  cancelPendingPatch();

  const visibleRows = getVisibleRows();
  heatMax = getHeatMax(visibleRows);
  motionEffects.revealRows(table.render(visibleRows, getRowRenderContext()));
  renderHighOi7d();
  filterBar.render();
  sortableHeaders.render();
}

function getVisibleRows() {
  const deps = [
    rankingData.getVersion(),
    filters.getVersion(),
    sort.getVersion(),
    favorites.getVersion(),
  ].join(":");

  if (visibleRowsCache.deps !== deps) {
    visibleRowsCache = {
      deps,
      rows: buildVisibleRows(
        rankingData.getRows(),
        filters.getState(),
        sort.getState(),
        favorites.getSet(),
      ),
    };
  }

  return visibleRowsCache.rows;
}

function getRowRenderContext() {
  return {
    favorites: favorites.getSet(),
    hasSourceRows: rankingData.getRows().length > 0,
    heatMax,
  };
}

function syncLivePriceHeatScale() {
  const nextHeatMax = getHeatMax(visibleRowsCache.rows);
  if (nextHeatMax.priceChangePercent === heatMax.priceChangePercent) return false;

  heatMax = nextHeatMax;
  return true;
}

function scheduleHighOi7dRender() {
  if (fullRenderFrame || highOi7dFrame) return;
  highOi7dFrame = window.requestAnimationFrame(() => {
    highOi7dFrame = 0;
    renderHighOi7d();
  });
}

function renderHighOi7d() {
  const rows = rankingData.getRows();
  motionEffects.revealRows(
    highOi7dTable.render(buildHighOi7dRows(rows), rows.length > 0),
  );
}

function cancelPendingPatch() {
  if (patchFrame) {
    window.cancelAnimationFrame(patchFrame);
    patchFrame = 0;
  }
  if (highOi7dFrame) {
    window.cancelAnimationFrame(highOi7dFrame);
    highOi7dFrame = 0;
  }
  pendingPatchSymbols.clear();
}

function cancelScheduledRenders() {
  if (fullRenderFrame) {
    window.cancelAnimationFrame(fullRenderFrame);
    fullRenderFrame = 0;
  }
  cancelPendingPatch();
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
