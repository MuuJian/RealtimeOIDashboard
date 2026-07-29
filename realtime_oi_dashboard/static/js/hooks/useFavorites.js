export function useFavorites(storageKey) {
  const favorites = readFavorites(storageKey);

  function save() {
    try {
      localStorage.setItem(storageKey, JSON.stringify([...favorites]));
    } catch {
      // Favorites still work for the current page when storage is unavailable.
    }
  }

  function toggle(symbol) {
    const normalizedSymbol = normalizeSymbol(symbol);
    if (!normalizedSymbol) return false;

    if (favorites.has(normalizedSymbol)) {
      favorites.delete(normalizedSymbol);
    } else {
      favorites.add(normalizedSymbol);
    }
    save();
    return true;
  }

  function pruneInactive(activeSymbols) {
    const active = new Set(
      activeSymbols.map(normalizeSymbol).filter(Boolean),
    );
    if (!active.size) return false;

    let changed = false;
    for (const symbol of favorites) {
      if (active.has(symbol)) continue;
      favorites.delete(symbol);
      changed = true;
    }
    if (changed) save();
    return changed;
  }

  return {
    pruneInactive,
    toggle,
    getSet() {
      return favorites;
    },
  };
}

function readFavorites(storageKey) {
  try {
    const raw = JSON.parse(localStorage.getItem(storageKey) || "[]");
    return new Set(
      Array.isArray(raw)
        ? raw.map(normalizeSymbol).filter(Boolean)
        : [],
    );
  } catch {
    return new Set();
  }
}

function normalizeSymbol(symbol) {
  return typeof symbol === "string" ? symbol.trim().toUpperCase() : "";
}
