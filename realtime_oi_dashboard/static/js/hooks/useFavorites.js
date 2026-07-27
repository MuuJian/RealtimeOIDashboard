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

  return {
    toggle,
    getSet() {
      return favorites;
    },
    get size() {
      return favorites.size;
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
