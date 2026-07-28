import { computeRankingView } from "../utils/rankingEngine.js";

const rowsBySymbol = new Map();

self.onmessage = event => {
  const message = event.data;
  if (!message || message.type !== "compute") return;

  if (message.replaceRows) {
    rowsBySymbol.clear();
    for (const row of message.replaceRows) rowsBySymbol.set(row.symbol, row);
  }
  for (const row of message.patchRows || []) {
    rowsBySymbol.set(row.symbol, row);
  }

  const view = computeRankingView(
    [...rowsBySymbol.values()],
    message.filters,
    message.sort,
    new Set(message.favorites),
    message.signalFilters,
  );
  self.postMessage({
    type: "result",
    requestId: message.requestId,
    view,
  });
};
