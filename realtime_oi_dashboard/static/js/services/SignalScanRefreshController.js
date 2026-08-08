import { loadSignalScanSnapshot } from "../data/SignalScanApiClient.js";

const DEFAULT_REFRESH_INTERVAL_MS = 30000;
const MAX_TIMER_DELAY_MS = 2_147_483_647;

export function createSignalScanRefreshController({
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
  const activeRequestControllers = new Set();
  let requestPromise = null;
  let requestGeneration = null;
  let queuedRefresh = null;
  let requestSequence = 0;
  let activeRequestSequence = null;
  let disposed = false;
  let generation = 0;
  let active = false;

  function start() {
    if (disposed || active) return;
    active = true;
    startGeneration();
  }

  function stop() {
    active = false;
    cancelGeneration();
  }

  function startGeneration() {
    if (
      disposed
      || !active
      || refreshTimer !== null
    ) return;
    const currentGeneration = ++generation;
    scheduleRefresh(currentGeneration);
    refreshTimer = window.setInterval(
      () => scheduleRefresh(currentGeneration),
      refreshIntervalMs,
    );
  }

  function cancelGeneration() {
    generation += 1;
    if (refreshTimer !== null) {
      window.clearInterval(refreshTimer);
      refreshTimer = null;
    }
    requestController?.abort();
    for (const controller of activeRequestControllers) controller.abort();
    activeRequestControllers.clear();
  }

  function scheduleRefresh(currentGeneration) {
    if (disposed || currentGeneration !== generation) return;
    if (requestPromise) {
      if (requestGeneration === currentGeneration) return;
      // An aborted request settles asynchronously. Queue the new generation
      // behind it so a stop/start cycle still refreshes immediately.
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
    const currentSequence = ++requestSequence;
    activeRequestControllers.add(currentController);
    requestController = currentController;
    requestGeneration = currentGeneration;
    activeRequestSequence = currentSequence;
    const currentPromise = runRefresh(
      currentGeneration,
      currentController,
      currentSequence,
    );
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

  async function runRefresh(
    currentGeneration,
    currentController,
    currentSequence,
  ) {
    const callbackContext = createCallbackContext(
      currentGeneration,
      currentController,
      currentSequence,
    );
    let callbackDispatched = false;
    try {
      let payload;
      try {
        payload = await loadSignalScanSnapshot({
          signal: currentController.signal,
        });
      } catch (error) {
        if (disposed || currentGeneration !== generation) return;
        if (error?.code === "ABORTED" && error?.reason === "cancelled") {
          return;
        }
        callbackDispatched = true;
        dispatchError(error, callbackContext, currentController);
        return;
      }

      if (disposed || currentGeneration !== generation) return;
      callbackDispatched = true;
      dispatchPayload(payload, callbackContext, currentController);
    } finally {
      if (requestController === currentController) requestController = null;
      if (!callbackDispatched) releaseRequestController(currentController);
    }
  }

  function createCallbackContext(
    currentGeneration,
    currentController,
    currentSequence,
  ) {
    return Object.freeze({
      signal: currentController.signal,
      generation: currentGeneration,
      isCurrent: () => (
        !disposed
        && active
        && generation === currentGeneration
        && activeRequestSequence === currentSequence
        && !currentController.signal.aborted
      ),
    });
  }

  function dispatchPayload(payload, callbackContext, currentController) {
    let callbackResult;
    try {
      callbackResult = onPayload(payload, callbackContext);
    } catch (error) {
      return dispatchError(error, callbackContext, currentController);
    }
    return trackCallback(callbackResult, callbackContext, callbackError => (
      dispatchError(callbackError, callbackContext, currentController)
    ), currentController);
  }

  function dispatchError(error, callbackContext, currentController) {
    if (!callbackContext.isCurrent()) {
      releaseRequestController(currentController);
      return;
    }
    let callbackResult;
    try {
      callbackResult = onError(error, callbackContext);
    } catch (callbackError) {
      console.error("signal scan error handler failed", callbackError);
      releaseRequestController(currentController);
      return;
    }
    return trackCallback(callbackResult, callbackContext, callbackError => {
      console.error("signal scan error handler failed", callbackError);
    }, currentController);
  }

  function trackCallback(result, callbackContext, onFailure, currentController) {
    return Promise.resolve(result)
      .catch(error => {
        if (!callbackContext.isCurrent()) return undefined;
        return onFailure(error);
      })
      .finally(() => releaseRequestController(currentController));
  }

  function releaseRequestController(controller) {
    activeRequestControllers.delete(controller);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    stop();
  }

  return {
    dispose,
    isRunning: () => active && refreshTimer !== null,
    refresh,
    start,
    stop,
  };
}
