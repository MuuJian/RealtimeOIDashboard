export function createDashboardStatus({
  title,
  detail,
  oiLoaded,
  marketCapLoaded,
}) {
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
    detail.textContent = [
      savedAt,
      errorText,
      batchError,
    ].join("");
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
    title.textContent = message;
    detail.textContent = error.message;
  }

  return {
    renderConnectionError,
    renderPayload,
    renderRankingError,
  };
}
