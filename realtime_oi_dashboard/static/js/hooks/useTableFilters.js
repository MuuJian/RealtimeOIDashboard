export function useTableFilters(initialState = {}) {
  const state = {
    query: "",
    limit: 99999,
    minOiValue: 0,
    minVolume: 0,
    favoritesOnly: false,
    ...initialState,
  };

  function update(nextState) {
    let changed = false;
    for (const [key, value] of Object.entries(nextState)) {
      if (state[key] !== value) {
        state[key] = value;
        changed = true;
      }
    }
    return changed;
  }

  return {
    setQuery(query) {
      return update({ query });
    },
    setLimit(limit) {
      return update({ limit: safeNumber(limit, 99999) });
    },
    setMinOiValue(minOiValue) {
      return update({ minOiValue: safeNumber(minOiValue, 0) });
    },
    setMinVolume(minVolume) {
      return update({ minVolume: safeNumber(minVolume, 0) });
    },
    toggleFavoritesOnly() {
      return update({ favoritesOnly: !state.favoritesOnly });
    },
    getState() {
      return state;
    },
  };
}

function safeNumber(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}
