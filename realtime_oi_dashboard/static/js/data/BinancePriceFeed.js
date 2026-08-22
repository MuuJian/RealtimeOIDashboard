import {
  mergeTickerUpdate,
  parseUsdMMarketTickerMessage,
} from "../utils/binanceTicker.js";

const TICKER_STALE_TIMEOUT_MS = 15000;
const RECONNECT_MAX_DELAY_MS = 30000;
const RECONNECT_ATTEMPT_CAP = 6;
const TICKER_STREAM_URL =
  "wss://fstream.binance.com/market/stream?streams=!ticker@arr";

export function createBinancePriceFeed() {
  const priceMap = new Map();
  const pendingSymbols = new Set();
  const priceListeners = new Set();
  const statusListeners = new Set();
  let socket = null;
  let reconnectTimer = 0;
  let staleTimer = 0;
  let flushFrame = 0;
  let stopped = true;
  let reconnectAttempts = 0;
  let status = "paused";

  function connect() {
    stopped = false;
    window.clearTimeout(reconnectTimer);
    reconnectTimer = 0;
    clearStaleTimer();

    const previousSocket = socket;
    socket = null;
    closeSocketQuietly(previousSocket);
    clearLivePricesAndNotify();

    let nextSocket;
    try {
      nextSocket = new WebSocket(TICKER_STREAM_URL);
    } catch {
      setStatus("error");
      scheduleReconnect();
      return;
    }
    socket = nextSocket;
    setStatus("connecting");
    armStaleTimer(nextSocket);

    nextSocket.onopen = () => {
      if (socket !== nextSocket || stopped) {
        closeSocketQuietly(nextSocket);
        return;
      }
      setStatus("live");
      armStaleTimer(nextSocket);
    };

    nextSocket.onmessage = event => {
      if (socket !== nextSocket || stopped) return;

      const updates = parseUsdMMarketTickerMessage(event.data);
      if (!updates.length) return;
      reconnectAttempts = 0;
      armStaleTimer(nextSocket);

      for (const { symbol, ticker } of updates) {
        const previous = priceMap.get(symbol);
        const nextTicker = mergeTickerUpdate(previous, ticker);
        if (!tickerChanged(previous, nextTicker)) continue;
        priceMap.set(symbol, nextTicker);
        pendingSymbols.add(symbol);
      }

      if (pendingSymbols.size) scheduleFlush();
    };

    nextSocket.onclose = () => {
      if (socket !== nextSocket) return;
      socket = null;
      clearStaleTimer();
      try {
        clearLivePricesAndNotify();
      } finally {
        if (!stopped) scheduleReconnect();
      }
    };

    nextSocket.onerror = () => {
      if (socket !== nextSocket || stopped) return;
      setStatus("error");
      if (nextSocket.readyState === WebSocket.CONNECTING) {
        abandonConnectingSocket(nextSocket);
        return;
      }
      closeSocketQuietly(nextSocket);
    };
  }

  function close() {
    stopped = true;
    window.clearTimeout(reconnectTimer);
    reconnectTimer = 0;
    clearStaleTimer();
    reconnectAttempts = 0;

    const currentSocket = socket;
    socket = null;
    closeSocketQuietly(currentSocket);
    clearLivePricesAndNotify();
    setStatus("paused");
  }

  function subscribePrices(listener) {
    priceListeners.add(listener);
    return () => priceListeners.delete(listener);
  }

  function subscribeStatus(listener) {
    statusListeners.add(listener);
    listener(status);
    return () => statusListeners.delete(listener);
  }

  function scheduleReconnect() {
    if (stopped || reconnectTimer) return;
    setStatus("reconnecting");
    reconnectAttempts = Math.min(reconnectAttempts + 1, RECONNECT_ATTEMPT_CAP);
    const delay = Math.min(
      1000 * 2 ** (reconnectAttempts - 1),
      RECONNECT_MAX_DELAY_MS,
    );
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = 0;
      connect();
    }, delay);
  }

  function armStaleTimer(currentSocket) {
    clearStaleTimer();
    staleTimer = window.setTimeout(() => {
      staleTimer = 0;
      if (socket !== currentSocket || stopped) return;
      setStatus("error");
      if (currentSocket.readyState === WebSocket.CONNECTING) {
        abandonConnectingSocket(currentSocket);
        return;
      }
      closeSocketQuietly(currentSocket);
    }, TICKER_STALE_TIMEOUT_MS);
  }

  function abandonConnectingSocket(currentSocket) {
    if (socket !== currentSocket) return;
    socket = null;
    clearStaleTimer();
    closeSocketQuietly(currentSocket);
    clearLivePricesAndNotify();
    scheduleReconnect();
  }

  function clearStaleTimer() {
    if (!staleTimer) return;
    window.clearTimeout(staleTimer);
    staleTimer = 0;
  }

  function scheduleFlush() {
    if (flushFrame) return;
    flushFrame = window.requestAnimationFrame(() => {
      flushFrame = 0;
      if (!pendingSymbols.size) return;

      const changedSymbols = new Set(pendingSymbols);
      pendingSymbols.clear();
      notifyPriceListeners(changedSymbols);
    });
  }

  function clearLivePricesAndNotify() {
    const changedSymbols = new Set(priceMap.keys());
    clearLivePrices();
    if (changedSymbols.size) notifyPriceListeners(changedSymbols);
  }

  function clearLivePrices() {
    priceMap.clear();
    pendingSymbols.clear();
    if (flushFrame) {
      window.cancelAnimationFrame(flushFrame);
      flushFrame = 0;
    }
  }

  function notifyPriceListeners(changedSymbols) {
    for (const listener of priceListeners) {
      listener(changedSymbols, priceMap);
    }
  }

  function setStatus(nextStatus) {
    if (status === nextStatus) return;
    status = nextStatus;
    for (const listener of statusListeners) {
      listener(status);
    }
  }

  return {
    close,
    connect,
    getPrices() {
      return priceMap;
    },
    subscribePrices,
    subscribeStatus,
  };
}

function tickerChanged(previous, nextTicker) {
  return (
    !previous
    || previous.price !== nextTicker.price
    || previous.volume24h !== nextTicker.volume24h
    || previous.priceChangePercent !== nextTicker.priceChangePercent
  );
}

function closeSocketQuietly(socket) {
  if (!socket || socket.readyState >= WebSocket.CLOSING) return;
  try {
    socket.close();
  } catch {
    // Browsers may reject close() while the handshake is still CONNECTING.
    // Its eventual onopen handler will detect that it is obsolete and retire it.
  }
}
