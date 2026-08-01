function sortableNumber(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function applyLivePriceToRow(row, live) {
  if (!row) return false;
  if (!live || !Number.isFinite(live.price) || live.price <= 0) {
    return syncOiToMarketCapRatio(row);
  }

  let changed = false;
  const price = live.price;
  const volume24h = Number.isFinite(live.volume24h) && live.volume24h >= 0
    ? live.volume24h
    : undefined;

  if (row.price !== price) {
    row.price = price;
    changed = true;
  }

  if (
    Number.isFinite(live.priceChangePercent)
    && row.priceChangePercent !== live.priceChangePercent
  ) {
    row.priceChangePercent = live.priceChangePercent;
    changed = true;
  }

  const price7dBaseline = Number(row.price7dBaseline);
  if (Number.isFinite(price7dBaseline) && price7dBaseline > 0) {
    const price7dChangePercent = (price - price7dBaseline)
      / price7dBaseline
      * 100;
    if (
      Number.isFinite(price7dChangePercent)
      && row.price7dChangePercent !== price7dChangePercent
    ) {
      row.price7dChangePercent = price7dChangePercent;
      changed = true;
    }
  }

  const currentOi = Number(row.currentOi);
  if (Number.isFinite(currentOi) && currentOi >= 0) {
    const currentOiValue = currentOi * price;
    if (Number.isFinite(currentOiValue) && row.currentOiValue !== currentOiValue) {
      row.currentOiValue = currentOiValue;
      changed = true;
    }
  }

  if (volume24h !== undefined && row.volume24h !== volume24h) {
    row.volume24h = volume24h;
    changed = true;
  }

  return syncOiToMarketCapRatio(row) || changed;
}

export function syncOiToMarketCapRatio(row) {
  const oiValue = Number(row.currentOiValue);
  const marketCap = Number(row.marketCap);
  const nextRatio = Number.isFinite(oiValue)
    && oiValue >= 0
    && Number.isFinite(marketCap)
    && marketCap > 0
    ? oiValue / marketCap
    : null;

  if (row.oiToMarketCapRatio === nextRatio) return false;
  row.oiToMarketCapRatio = nextRatio;
  return true;
}

function filterRankingRows(rows, filters, favorites) {
  const query = filters.query.trim().toUpperCase();
  const minOiValue = Number(filters.minOiValue || 0);
  const minVolume = Number(filters.minVolume || 0);

  return rows.filter(row => {
    if (query && !String(row.symbol || "").toUpperCase().includes(query)) return false;
    if (filters.favoritesOnly && !favorites.has(row.symbol)) return false;
    if (minOiValue && Number(row.currentOiValue || 0) < minOiValue) return false;
    if (minVolume && Number(row.volume24h || 0) < minVolume) return false;
    return true;
  });
}

function sortRankingRows(rows, sortState) {
  const dir = sortState.sortDir === "asc" ? 1 : -1;
  const sorted = rows.slice();

  sorted.sort((a, b) => {
    if (sortState.sortKey === "symbol") return a.symbol.localeCompare(b.symbol) * dir;

    const left = sortableNumber(a[sortState.sortKey]);
    const right = sortableNumber(b[sortState.sortKey]);
    if (left == null && right == null) return 0;
    if (left == null) return 1;
    if (right == null) return -1;
    return (left - right) * dir;
  });

  return sorted;
}

export function buildVisibleRows(rows, filters, sortState, favorites) {
  const limit = sortableNumber(filters.limit);
  return sortRankingRows(filterRankingRows(rows, filters, favorites), sortState)
    .slice(0, limit != null && limit >= 0 ? limit : 99999);
}

export function buildHighOi7dRows(
  rows,
  {
    minOi7dChangePercent = 100,
    minOiValue = 10000000,
  } = {},
) {
  return rows
    .filter(
      row => Number(row.oi7dChangePercent || 0) > minOi7dChangePercent,
    )
    .filter(row => Number(row.currentOiValue || 0) > minOiValue)
    .slice()
    .sort((a, b) => Number(b.oi7dChangePercent || 0) - Number(a.oi7dChangePercent || 0));
}

export function getHeatMax(rows) {
  const maximums = {
    fundingRatePercent: 0,
    priceChangePercent: 0,
    price7dChangePercent: 0,
    oi24hChangePercent: 0,
    oi7dChangePercent: 0,
  };

  for (const row of rows) {
    maximums.fundingRatePercent = largerAbsolute(
      maximums.fundingRatePercent,
      row.fundingRatePercent,
    );
    maximums.priceChangePercent = largerAbsolute(
      maximums.priceChangePercent,
      row.priceChangePercent,
    );
    maximums.price7dChangePercent = largerAbsolute(
      maximums.price7dChangePercent,
      row.price7dChangePercent,
    );
    maximums.oi24hChangePercent = largerAbsolute(
      maximums.oi24hChangePercent,
      row.oi24hChangePercent,
    );
    maximums.oi7dChangePercent = largerAbsolute(
      maximums.oi7dChangePercent,
      row.oi7dChangePercent,
    );
  }

  return maximums;
}

function largerAbsolute(current, value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(current, Math.abs(number)) : current;
}
