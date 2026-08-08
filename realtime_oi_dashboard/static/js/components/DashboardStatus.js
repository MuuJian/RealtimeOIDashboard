export function createDashboardStatus({
  title,
  detail,
  oiLoaded,
  marketCapLoaded,
}) {
  let clockTimer = null;
  let clockOffsetMinutes = null;
  let clockSuffix = "";

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
      clockOffsetMinutes = timestampOffsetMinutes(payload.saved_at);
      detail.title = `最近一次 OI 更新：${savedAt}`;
      renderClock();
      startClock();
    } else {
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
    detail.textContent = `${formatClock(new Date(), clockOffsetMinutes)}${clockSuffix}`;
  }

  return {
    dispose: stopClock,
    renderConnectionError,
    renderPayload,
    renderRankingError,
  };
}

function timestampOffsetMinutes(timestamp) {
  if (timestamp.endsWith("Z")) return 0;
  const match = timestamp.match(/([+-])(\d{2}):(\d{2})$/);
  if (!match) return -new Date().getTimezoneOffset();

  const minutes = Number(match[2]) * 60 + Number(match[3]);
  return match[1] === "-" ? -minutes : minutes;
}

function formatClock(date, offsetMinutes) {
  const shifted = new Date(date.getTime() + offsetMinutes * 60 * 1000);
  const datePart = [
    shifted.getUTCFullYear(),
    twoDigits(shifted.getUTCMonth() + 1),
    twoDigits(shifted.getUTCDate()),
  ].join("-");
  const timePart = [
    twoDigits(shifted.getUTCHours()),
    twoDigits(shifted.getUTCMinutes()),
    twoDigits(shifted.getUTCSeconds()),
  ].join(":");
  const sign = offsetMinutes < 0 ? "-" : "+";
  const absoluteOffset = Math.abs(offsetMinutes);
  const offset = `${sign}${twoDigits(Math.floor(absoluteOffset / 60))}`
    + `:${twoDigits(absoluteOffset % 60)}`;
  return `${datePart} ${timePart} ${offset}`;
}

function twoDigits(value) {
  return String(value).padStart(2, "0");
}
