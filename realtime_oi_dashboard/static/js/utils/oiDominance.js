const PRIMARY_MARKETS = Object.freeze([
  { key: "btc", label: "BTC", symbol: "BTCUSDT" },
  { key: "eth", label: "ETH", symbol: "ETHUSDT" },
  { key: "sol", label: "SOL", symbol: "SOLUSDT" },
]);

const PRIMARY_SYMBOLS = new Map(
  PRIMARY_MARKETS.map(market => [market.symbol, market.key]),
);

export function buildOiDominance(rows) {
  const points = [
    buildPoint(rows, "7d"),
    buildPoint(rows, "24h"),
    buildPoint(rows, "now"),
  ];
  const current = points[2];
  return { ...current, points };
}

function buildPoint(rows, period) {
  const values = new Map([
    ["btc", 0],
    ["eth", 0],
    ["sol", 0],
    ["other", 0],
  ]);

  for (const row of rows || []) {
    const value = oiValueAt(row, period);
    if (!Number.isFinite(value) || value <= 0) continue;
    const key = PRIMARY_SYMBOLS.get(row.symbol) || "other";
    values.set(key, values.get(key) + value);
  }

  const total = [...values.values()].reduce((sum, value) => sum + value, 0);
  const groups = [
    ...PRIMARY_MARKETS.map(({ key, label }) => ({ key, label })),
    { key: "other", label: "OTHER" },
  ].map(group => {
    const value = values.get(group.key);
    return {
      ...group,
      value,
      percent: total > 0 ? value / total * 100 : 0,
    };
  });

  return { total, groups };
}

function oiValueAt(row, period) {
  const currentOi = positiveNumber(row?.currentOi);
  const currentPrice = positiveNumber(row?.price);
  if (currentOi == null || currentPrice == null) return null;
  if (period === "now") return currentOi * currentPrice;

  if (period === "24h") {
    const pastOi = reversePercentChange(currentOi, row.oi24hChangePercent);
    const pastPrice = reversePercentChange(currentPrice, row.priceChangePercent);
    return pastOi != null && pastPrice != null ? pastOi * pastPrice : null;
  }

  const pastOi = reversePercentChange(currentOi, row.oi7dChangePercent);
  const pastPrice = positiveNumber(row.price7dBaseline);
  return pastOi != null && pastPrice != null ? pastOi * pastPrice : null;
}

function reversePercentChange(current, changePercent) {
  const change = Number(changePercent);
  if (!Number.isFinite(change)) return null;
  const ratio = 1 + change / 100;
  if (ratio <= 0) return null;
  return current / ratio;
}

function positiveNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}
