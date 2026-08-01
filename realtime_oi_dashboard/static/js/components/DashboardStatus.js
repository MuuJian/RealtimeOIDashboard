export function createDashboardStatus({ title, detail }) {
  function renderPayload(payload) {
    const loadedSymbols = payload.rows.length;
    title.textContent = payload.error
      ? "OI 更新异常"
      : loadedSymbols ? "实时 OI 变化" : "等待本次 OI 数据";

    const errorCount = payload.recent_errors?.length || 0;
    const errorText = errorCount ? ` · 错误 ${errorCount}` : "";
    const batchError = typeof payload.error === "string" && payload.error
      ? ` · ${payload.error}`
      : "";
    const savedAt = payload.saved_at || "尚无 OI";
    const totalSymbols = payload.total_symbols || 0;
    detail.textContent = [
      `${savedAt} · 已加载 ${loadedSymbols}/${totalSymbols}`,
      errorText,
      batchError,
    ].join("");
  }

  function renderConnectionError(error) {
    renderError("OI 连接异常", error);
  }

  function renderRankingError(error) {
    renderError("排行计算异常", error);
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
