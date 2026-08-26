import { formatUtc8DateTime } from "../utils/format.js";

export function createDashboardStatus({
  title,
  detail,
  oiLoaded,
  marketCapLoaded,
}) {
  let clockTimer = null;
  let clockSuffix = "";
  let clockAvailable = false;
  let paused = false;

  function renderPayload(payload) {
    const loadedSymbols = payload.rows.length;
    title.textContent = payload.error
      ? "OI 更新異常"
      : loadedSymbols ? "實時 OI 變化" : "等待本次 OI 數據";

    const errorCount = payload.recent_errors?.length || 0;
    const errorText = errorCount ? ` · 錯誤 ${errorCount}` : "";
    const batchError = typeof payload.error === "string" && payload.error
      ? ` · ${payload.error}`
      : "";
    const savedAt = payload.saved_at || "尚無 OI";
    const totalSymbols = payload.total_symbols || 0;
    const marketCapSymbols = payload.market_cap_loaded_symbols || 0;
    clockSuffix = `${errorText}${batchError}`;
    if (payload.saved_at && Number.isFinite(Date.parse(payload.saved_at))) {
      clockAvailable = true;
      detail.title = `最近一次 OI 更新：${formatUtc8DateTime(savedAt)}`;
      renderClock();
      if (paused) {
        stopClock();
      } else {
        startClock();
      }
    } else {
      clockAvailable = false;
      stopClock();
      detail.title = "";
      detail.textContent = `${savedAt}${clockSuffix}`;
    }
    oiLoaded.textContent = `${loadedSymbols}/${totalSymbols}`;
    marketCapLoaded.textContent = `${marketCapSymbols}/${totalSymbols}`;
  }

  function renderConnectionError(error) {
    renderError("OI 連接異常", error);
  }

  function renderRankingError(error) {
    renderError("排行計算異常", error);
  }

  function renderError(message, error) {
    clockAvailable = false;
    stopClock();
    title.textContent = message;
    detail.title = "";
    detail.textContent = error.message;
  }

  function startClock() {
    if (clockTimer !== null) return;
    clockTimer = window.setInterval(renderClock, 1000);
  }

  function stopClock() {
    if (clockTimer === null) return;
    window.clearInterval(clockTimer);
    clockTimer = null;
  }

  function renderClock() {
    detail.textContent = `${formatUtc8DateTime(new Date())}${clockSuffix}`;
  }

  function setPaused(nextPaused) {
    paused = Boolean(nextPaused);
    if (paused || !clockAvailable) {
      stopClock();
      return;
    }
    renderClock();
    startClock();
  }

  return {
    dispose() {
      clockAvailable = false;
      stopClock();
    },
    renderConnectionError,
    renderPayload,
    renderRankingError,
    setPaused,
  };
}
