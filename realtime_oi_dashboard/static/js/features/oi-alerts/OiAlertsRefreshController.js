import { loadOiAlerts } from "./OiAlertsApiClient.js";

const DEFAULT_REFRESH_INTERVAL_MS = 10000;
const MAX_TIMER_DELAY_MS = 2_147_483_647;

export function createOiAlertsRefreshController({
  onPayload,
  onError,
  refreshIntervalMs = DEFAULT_REFRESH_INTERVAL_MS,
}) {
  if (typeof onPayload !== "function" || typeof onError !== "function") {
    throw new TypeError("onPayload and onError must be functions");
  }
  if (
    !Number.isFinite(refreshIntervalMs)
    || refreshIntervalMs <= 0
    || refreshIntervalMs > MAX_TIMER_DELAY_MS
  ) {
    throw new TypeError(
      "refreshIntervalMs must be a positive number within timer range",
    );
  }

  let refreshTimer = null;
  let requestController = null;
  let requestPromise = null;
  let requestGeneration = null;
  let queuedRefresh = null;
  let disposed = false;
  let active = false;
  let generation = 0;

  function start() {
    if (disposed || active) return;
    active = true;
    const currentGeneration = ++generation;
    scheduleRefresh(currentGeneration);
    refreshTimer = window.setInterval(
      () => scheduleRefresh(currentGeneration),
      refreshIntervalMs,
    );
  }

  function stop() {
    active = false;
    generation += 1;
    if (refreshTimer !== null) {
      window.clearInterval(refreshTimer);
      refreshTimer = null;
    }
    requestController?.abort();
  }

  function scheduleRefresh(currentGeneration) {
    if (disposed || !active || currentGeneration !== generation) return;
    if (requestPromise) {
      if (requestGeneration === currentGeneration) return;
      queueRefresh(currentGeneration, requestPromise);
      return;
    }
    queuedRefresh = null;
    void refresh(currentGeneration);
  }

  function queueRefresh(currentGeneration, pendingPromise) {
    if (
      queuedRefresh?.promise === pendingPromise
      && queuedRefresh.generation === currentGeneration
    ) return;
    queuedRefresh = { generation: currentGeneration, promise: pendingPromise };
    const continueRefresh = () => {
      if (
        queuedRefresh?.promise !== pendingPromise
        || queuedRefresh.generation !== currentGeneration
      ) return;
      queuedRefresh = null;
      scheduleRefresh(currentGeneration);
    };
    void pendingPromise.then(continueRefresh, continueRefresh);
  }

  async function refresh(currentGeneration = generation) {
    if (
      requestPromise
      || disposed
      || !active
      || currentGeneration !== generation
    ) return;
    const currentController = new AbortController();
    requestController = currentController;
    requestGeneration = currentGeneration;
    const currentPromise = runRefresh(currentGeneration, currentController);
    requestPromise = currentPromise;
    try {
      return await currentPromise;
    } finally {
      if (requestPromise === currentPromise) {
        requestPromise = null;
        requestGeneration = null;
      }
    }
  }

  async function runRefresh(currentGeneration, currentController) {
    try {
      const payload = await loadOiAlerts({ signal: currentController.signal });
      if (!isCurrent(currentGeneration, currentController)) return;
      onPayload(payload, callbackContext(currentGeneration, currentController));
    } catch (error) {
      if (!isCurrent(currentGeneration, currentController)) return;
      if (error?.code === "ABORTED" && error?.reason === "cancelled") return;
      onError(error, callbackContext(currentGeneration, currentController));
    } finally {
      if (requestController === currentController) requestController = null;
    }
  }

  function callbackContext(currentGeneration, currentController) {
    return Object.freeze({
      signal: currentController.signal,
      generation: currentGeneration,
      isCurrent: () => isCurrent(currentGeneration, currentController),
    });
  }

  function isCurrent(currentGeneration, currentController) {
    return !disposed
      && active
      && currentGeneration === generation
      && !currentController.signal.aborted;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    stop();
  }

  return {
    dispose,
    isRunning: () => active && refreshTimer !== null,
    refresh: () => scheduleRefresh(generation),
    start,
    stop,
  };
}
