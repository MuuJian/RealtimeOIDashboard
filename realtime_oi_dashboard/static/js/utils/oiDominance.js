const PRIMARY_MARKETS = Object.freeze([
  { key: "btc", label: "BTC", symbol: "BTCUSDT" },
  { key: "eth", label: "ETH", symbol: "ETHUSDT" },
]);

const PRIMARY_SYMBOLS = new Map(
  PRIMARY_MARKETS.map(market => [market.symbol, market.key]),
);

export function buildOiDominance(rows, history = []) {
  const current = buildPoint(rows, "now");
  const historicalPoints = history.map(historyPoint);
  const chartPoints = current.total > 0
    ? [
      ...historicalPoints.filter(point => point.timestamp < current.timestamp),
      current,
    ]
    : historicalPoints;
  const points = chartPoints.length > 1
    ? chartPoints
    : [chartPoints[0] || current, chartPoints[0] || current];
  return { ...current, points };
}

function historyPoint(point) {
  return {
    timestamp: point.timestamp,
    total: 100,
    groups: [
      ...PRIMARY_MARKETS.map(({ key, label }) => ({
        key,
        label,
        value: Number(point[`${key}Value`]) || 0,
        percent: Number(point[key]) || 0,
      })),
      {
        key: "other",
        label: "OTHER",
        value: Number(point.otherValue) || 0,
        percent: Number(point.other) || 0,
      },
    ],
  };
}

function buildPoint(rows, period) {
  const values = new Map([
    ["btc", 0],
    ["eth", 0],
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

  return {
    timestamp: latestTimestamp(rows),
    total,
    groups,
  };
}

function latestTimestamp(rows) {
  const latest = (rows || []).reduce((latestTimestamp, row) => {
    const timestamp = Number(row?.oiUpdatedAt);
    return Number.isSafeInteger(timestamp) && timestamp > latestTimestamp
      ? timestamp
      : latestTimestamp;
  }, 0);
  return latest || Date.now();
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
