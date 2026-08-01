export function buildOiStats(rows) {
  let topIncrease = null;
  let topDecrease = null;

  for (const row of rows) {
    const change = row.oi24hChangePercent;
    if (change > 0 && (!topIncrease || change > topIncrease.oi24hChangePercent)) {
      topIncrease = row;
    } else if (
      change < 0
      && (!topDecrease || change < topDecrease.oi24hChangePercent)
    ) {
      topDecrease = row;
    }
  }

  return { topIncrease, topDecrease };
}
