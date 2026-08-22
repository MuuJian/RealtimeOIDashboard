import { computeRankingView } from "../utils/rankingEngine.js";

export function createRankingProcessor() {
  const rowsBySymbol = new Map();
  let nextRequestId = 0;
  let worker = createWorker();
  let disposed = false;
  let inFlight = null;
  let queued = null;

  if (worker) {
    worker.onmessage = handleWorkerMessage;
    worker.onerror = handleWorkerFailure;
    worker.onmessageerror = handleWorkerFailure;
  }

  function request({
    replaceRows,
    patchRows = [],
    filters,
    sort,
    favorites,
    signalFilters,
  }) {
    if (disposed) return Promise.reject(new Error("ranking processor disposed"));

    updateLocalRows(replaceRows, patchRows);
    const requestId = ++nextRequestId;
    const view = {
      filters: { ...filters },
      sort: { ...sort },
      favorites: [...favorites],
      signalFilters: { ...signalFilters },
    };

    if (!worker) {
      return Promise.resolve().then(() => computeLocalView(view));
    }

    return new Promise((resolve, reject) => {
      const job = {
        requestId,
        replaceRows,
        patchRows,
        view,
        rejecters: [reject],
        resolvers: [resolve],
      };
      if (inFlight) {
        queueLatest(job);
      } else {
        sendJob(job);
      }
    });
  }

  function handleWorkerMessage(event) {
    const result = event.data;
    if (
      !result
      || result.type !== "result"
      || !inFlight
      || result.requestId !== inFlight.requestId
    ) return;

    const completed = inFlight;
    inFlight = null;
    for (const resolve of completed.resolvers) resolve(result.view);
    sendQueuedJob();
  }

  function handleWorkerFailure(event) {
    event?.preventDefault?.();
    worker?.terminate();
    worker = null;
    if (inFlight) {
      settleLocally(inFlight);
      inFlight = null;
    }
    if (queued) {
      settleLocally(queued);
      queued = null;
    }
  }

  function queueLatest(job) {
    const rejecters = queued
      ? [...queued.rejecters, ...job.rejecters]
      : job.rejecters;
    const resolvers = queued
      ? [...queued.resolvers, ...job.resolvers]
      : job.resolvers;
    queued = {
      requestId: job.requestId,
      replaceRows: null,
      patchRows: [],
      view: job.view,
      rejecters,
      resolvers,
    };
  }

  function sendQueuedJob() {
    if (!queued || !worker || disposed) return;
    const job = queued;
    queued = null;
    job.replaceRows = [...rowsBySymbol.values()];
    sendJob(job);
  }

  function sendJob(job) {
    inFlight = job;
    try {
      worker.postMessage({
        type: "compute",
        requestId: job.requestId,
        replaceRows: job.replaceRows,
        patchRows: job.patchRows,
        ...job.view,
      });
    } catch {
      handleWorkerFailure();
    }
  }

  function updateLocalRows(replaceRows, patchRows) {
    if (replaceRows) {
      rowsBySymbol.clear();
      for (const row of replaceRows) rowsBySymbol.set(row.symbol, row);
    }
    for (const row of patchRows) rowsBySymbol.set(row.symbol, row);
  }

  function computeLocalView(view) {
    return computeRankingView(
      [...rowsBySymbol.values()],
      view.filters,
      view.sort,
      new Set(view.favorites),
      view.signalFilters,
    );
  }

  function settleLocally(job) {
    let view;
    try {
      view = computeLocalView(job.view);
    } catch (error) {
      for (const reject of job.rejecters) reject(error);
      return;
    }
    for (const resolve of job.resolvers) resolve(view);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    worker?.terminate();
    worker = null;
    if (inFlight) {
      settleLocally(inFlight);
      inFlight = null;
    }
    if (queued) {
      settleLocally(queued);
      queued = null;
    }
    rowsBySymbol.clear();
  }

  return {
    dispose,
    request,
  };
}

function createWorker() {
  if (typeof Worker !== "function") return null;
  try {
    return new Worker(
      new URL("../workers/rankingWorker.js", import.meta.url),
      { type: "module" },
    );
  } catch {
    return null;
  }
}
