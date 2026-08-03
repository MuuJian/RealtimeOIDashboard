import { loadSignalScanSnapshot } from "../data/SignalScanApiClient.js";

const DEFAULT_REFRESH_INTERVAL_MS = 30000;

export function createSignalScanRefreshController({
  onPayload,
  onError,
  refreshIntervalMs = DEFAULT_REFRESH_INTERVAL_MS,
}) {
  let refreshTimer = null;
  let refreshInFlight = false;
  let requestController = null;
  let disposed = false;

  function start() {
    if (disposed || refreshTimer !== null) return;
    refresh();
    refreshTimer = window.setInterval(refresh, refreshIntervalMs);
  }

  function stop() {
    if (refreshTimer !== null) {
      window.clearInterval(refreshTimer);
      refreshTimer = null;
    }
    requestController?.abort();
  }

  async function refresh() {
    if (refreshInFlight || disposed) return;
    refreshInFlight = true;
    const currentController = new AbortController();
    requestController = currentController;

    try {
      const payload = await loadSignalScanSnapshot({
        signal: currentController.signal,
      });
      if (disposed) return;
      onPayload(payload);
    } catch (error) {
      if (disposed) return;
      if (error.message === "訊號掃描请求已取消") return;
      onError(error);
    } finally {
      if (requestController === currentController) requestController = null;
      refreshInFlight = false;
    }
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    stop();
  }

  return {
    dispose,
    isRunning: () => refreshTimer !== null,
    refresh,
    start,
    stop,
  };
}
