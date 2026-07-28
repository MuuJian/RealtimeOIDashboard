export function useFavorites(
  storageKey,
  {
    seedSymbols = [],
    seedVersion = "",
  } = {},
) {
  const favorites = readFavorites(storageKey);
  seedFavorites(storageKey, favorites, seedSymbols, seedVersion);

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

function seedFavorites(storageKey, favorites, symbols, version) {
  if (!version) return;

  const markerKey = `${storageKey}:seed:${version}`;
  try {
    if (localStorage.getItem(markerKey) === "1") return;
  } catch {
    // Continue with in-memory favorites when storage is unavailable.
  }

  for (const symbol of symbols) {
    const normalizedSymbol = normalizeSymbol(symbol);
    if (normalizedSymbol) favorites.add(normalizedSymbol);
  }

  try {
    localStorage.setItem(storageKey, JSON.stringify([...favorites]));
    localStorage.setItem(markerKey, "1");
  } catch {
    // Seeded favorites still work for the current page.
  }
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
