const VALID_SORT_KEYS = new Set([
  "symbol",
  "price",
  "fundingRatePercent",
  "priceChangePercent",
  "price7dChangePercent",
  "currentOiValue",
  "marketCap",
  "oiToMarketCapRatio",
  "volume24h",
  "oi24hChangePercent",
  "oi7dChangePercent",
]);

export function useTableSort({
  storageKey = "",
  initialState = {},
} = {}) {
  const persistedState = readSortState(storageKey);
  const state = {
    sortKey: "currentOiValue",
    sortDir: "desc",
    ...initialState,
    ...persistedState,
  };

  function setSortKey(sortKey) {
    if (!VALID_SORT_KEYS.has(sortKey)) return false;
    const sortDir = state.sortKey === sortKey && state.sortDir === "desc"
      ? "asc"
      : "desc";
    return setSort(sortKey, sortDir);
  }

  function setSort(sortKey, sortDir) {
    if (
      !VALID_SORT_KEYS.has(sortKey)
      || !["asc", "desc"].includes(sortDir)
      || (state.sortKey === sortKey && state.sortDir === sortDir)
    ) return false;
    state.sortKey = sortKey;
    state.sortDir = sortDir;
    saveSortState(storageKey, state);
    return true;
  }

  return {
    setSort,
    setSortKey,
    getState() {
      return state;
    },
  };
}

function readSortState(storageKey) {
  if (!storageKey) return {};
  try {
    const value = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (
      !value
      || !VALID_SORT_KEYS.has(value.sortKey)
      || !["asc", "desc"].includes(value.sortDir)
    ) return {};
    return {
      sortKey: value.sortKey,
      sortDir: value.sortDir,
    };
  } catch {
    return {};
  }
}

function saveSortState(storageKey, state) {
  if (!storageKey) return;
  try {
    localStorage.setItem(storageKey, JSON.stringify({
      sortKey: state.sortKey,
      sortDir: state.sortDir,
    }));
  } catch {
    // Sorting still works for the current page when storage is unavailable.
  }
}
