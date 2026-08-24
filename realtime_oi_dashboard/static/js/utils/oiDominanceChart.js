export function dominancePointPositions(points) {
  const count = Array.isArray(points) ? points.length : 0;
  if (!count) return [];
  if (count === 1) return [0];

  const timestamps = points.map(point => Number(point?.timestamp));
  const chronological = timestamps.every((timestamp, index) => (
    Number.isFinite(timestamp)
    && (index === 0 || timestamp >= timestamps[index - 1])
  ));
  const span = timestamps[count - 1] - timestamps[0];
  if (!chronological || span <= 0) return evenlySpacedPositions(count);

  return timestamps.map(timestamp => (
    (timestamp - timestamps[0]) / span
  ));
}

export function dominancePointIndexAtRatio(points, ratio) {
  const positions = dominancePointPositions(points);
  if (!positions.length) return -1;

  const target = Number.isFinite(ratio)
    ? Math.max(0, Math.min(ratio, 1))
    : 0;
  let nearestIndex = 0;
  let nearestDistance = Number.POSITIVE_INFINITY;
  positions.forEach((position, index) => {
    const distance = Math.abs(position - target);
    if (distance > nearestDistance) return;
    nearestIndex = index;
    nearestDistance = distance;
  });
  return nearestIndex;
}

export function dominanceAriaLabel(dominance) {
  const hasCurrent = dominance?.total > 0;
  const point = hasCurrent ? dominance : dominance?.points?.at(-1);
  if (!point || point.total <= 0) return "OI 市場佔比暫無資料";

  const period = hasCurrent ? "當前" : "最近歷史";
  const shares = point.groups
    .map(group => `${group.label} ${group.percent.toFixed(1)}%`)
    .join("，");
  return `OI 市場佔比${period}：${shares}`;
}

function evenlySpacedPositions(count) {
  return Array.from(
    { length: count },
    (_, index) => index / (count - 1),
  );
}
