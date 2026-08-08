import { loadOiSnapshot } from "../data/OiApiClient.js";

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
  let requestController = null;
  let requestPromise = null;
  let requestGeneration = null;
  let queuedRefresh = null;
  let lastResponseAt = null;
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
    if (
      disposed
      || !active
      || currentGeneration !== generation
    ) return;
    if (requestPromise) {
      if (requestGeneration === currentGeneration) return;
      const pendingPromise = requestPromise;
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
      return;
    }
    queuedRefresh = null;
    void refresh(currentGeneration);
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
      const payload = await loadOiSnapshot({
        signal: currentController.signal,
      });
      if (!isCurrent(currentGeneration, currentController)) return;
      lastResponseAt = responseClock();
      onPayload(payload);
    } catch (error) {
      if (!isCurrent(currentGeneration, currentController)) return;
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
      if (isCurrent(currentGeneration, currentController)) onSettled();
    }
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
    isRunning() {
      return active && refreshTimer !== null;
    },
    refresh: () => scheduleRefresh(generation),
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
