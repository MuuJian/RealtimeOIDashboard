const PRIMARY_MARKETS = Object.freeze([
  { key: "btc", label: "BTC", symbol: "BTCUSDT" },
  { key: "eth", label: "ETH", symbol: "ETHUSDT" },
  { key: "sol", label: "SOL", symbol: "SOLUSDT" },
]);

const PRIMARY_SYMBOLS = new Map(
  PRIMARY_MARKETS.map(market => [market.symbol, market.key]),
);

export function buildOiDominance(rows) {
  const values = new Map([
    ["btc", 0],
    ["eth", 0],
    ["sol", 0],
    ["other", 0],
  ]);

  for (const row of rows || []) {
    const value = Number(row?.currentOiValue);
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
