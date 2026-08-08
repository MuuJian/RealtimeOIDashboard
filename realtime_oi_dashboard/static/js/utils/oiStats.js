export function buildOiStats(rows) {
  let topIncrease = null;
  let topDecrease = null;

  for (const row of rows) {
    const change = row.priceChangePercent;
    if (!Number.isFinite(change)) continue;
    if (change > 0 && (!topIncrease || change > topIncrease.priceChangePercent)) {
      topIncrease = row;
    } else if (
      change < 0
      && (!topDecrease || change < topDecrease.priceChangePercent)
    ) {
      topDecrease = row;
    }
  }

  return { topIncrease, topDecrease };
}
