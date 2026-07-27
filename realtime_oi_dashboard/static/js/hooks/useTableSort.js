export function useTableSort(initialState = {}) {
  const state = {
    sortKey: "oi24hChangePercent",
    sortDir: "desc",
    ...initialState,
  };

  function setSortKey(sortKey) {
    if (state.sortKey === sortKey) {
      state.sortDir = state.sortDir === "desc" ? "asc" : "desc";
    } else {
      state.sortKey = sortKey;
      state.sortDir = "desc";
    }
  }

  return {
    setSortKey,
    getState() {
      return state;
    },
  };
}
