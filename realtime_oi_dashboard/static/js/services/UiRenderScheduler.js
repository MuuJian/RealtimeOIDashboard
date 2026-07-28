export function createUiRenderScheduler(onFlush) {
  let frame = 0;
  let disposed = false;
  let pending = createPendingRender();

  function schedule({
    full = false,
    high = false,
    controls = false,
    stats = false,
    priceStatus,
    patchSymbols = [],
  } = {}) {
    if (disposed) return;

    if (full) {
      pending.full = true;
      pending.patchSymbols.clear();
    } else if (!pending.full) {
      for (const symbol of patchSymbols) pending.patchSymbols.add(symbol);
    }
    pending.high ||= high;
    pending.controls ||= controls;
    pending.stats ||= stats;
    if (priceStatus) pending.priceStatus = priceStatus;

    if (frame) return;
    frame = window.requestAnimationFrame(flush);
  }

  function flush() {
    frame = 0;
    if (disposed) return;

    const render = pending;
    pending = createPendingRender();
    onFlush(render);
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (frame) {
      window.cancelAnimationFrame(frame);
      frame = 0;
    }
    pending = createPendingRender();
  }

  return {
    dispose,
    schedule,
  };
}

function createPendingRender() {
  return {
    full: false,
    high: false,
    controls: false,
    stats: false,
    priceStatus: null,
    patchSymbols: new Set(),
  };
}
