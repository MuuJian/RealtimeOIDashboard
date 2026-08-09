import { loadOiSnapshot } from "./OiApiClient.js";

const DEFAULT_REFRESH_INTERVAL_MS = 10000;
const DEFAULT_MAX_STALE_MS = 15 * 60 * 1000;

export function createOiRefreshController({
  onPayload,
  onError,
  onSettled,
  refreshIntervalMs = DEFAULT_REFRESH_INTERVAL_MS,
  maxStaleMs = DEFAULT_MAX_STALE_MS,
}) {
  let refreshTimer = null;
  let refreshInFlight = false;
  let requestController = null;
  let lastResponseAt = null;
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
      const payload = await loadOiSnapshot({
        signal: currentController.signal,
      });
      if (disposed) return;
      lastResponseAt = responseClock();
      onPayload(payload);
    } catch (error) {
      if (disposed) return;
      if (error.message === "OI 請求已取消") return;

      const dataExpired = Boolean(
        lastResponseAt && isResponseStale(lastResponseAt, maxStaleMs),
      );
      if (dataExpired) lastResponseAt = null;
      onError(error, { dataExpired });
    } finally {
      if (requestController === currentController) {
        requestController = null;
      }
      refreshInFlight = false;
      if (!disposed) onSettled();
    }
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    stop();
  }

  return {
    dispose,
    isRunning() {
      return refreshTimer !== null;
    },
    refresh,
    start,
    stop,
  };
}

function responseClock() {
  return {
    wall: Date.now(),
    monotonic: performance.now(),
  };
}

function isResponseStale(previous, maxStaleMs) {
  return Date.now() - previous.wall > maxStaleMs
    || performance.now() - previous.monotonic > maxStaleMs;
}
