const STATUS_LABELS = {
  buying: "買盤主導",
  selling: "賣盤主導",
  neutral: "中性",
  collecting: "資料累積中",
  untracked: "未追蹤",
  unavailable: "資料不可用",
};
const HEALTH_LABELS = {
  warming: "資料累積中",
  stale: "資料延遲",
  partial: "資料不完整",
  unavailable: "資料不可用",
};

export function formatCvd(value, ratio) {
  if (!Number.isFinite(value) || !Number.isFinite(ratio)) return "-";
  const ratioPercent = ratio * 100;
  return `${formatSignedNotional(value)} · `
    + `${ratioPercent >= 0 ? "+" : ""}${ratioPercent.toFixed(1)}%`;
}

export function cvdStatusLabel(status, health = null) {
  if (health && health !== "live" && HEALTH_LABELS[health]) {
    return HEALTH_LABELS[health];
  }
  return STATUS_LABELS[status] || STATUS_LABELS.unavailable;
}

function formatSignedNotional(value) {
  const absolute = Math.abs(value);
  const units = [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  const [divisor, suffix] = units.find(([threshold]) => absolute >= threshold)
    || [1, ""];
  const digits = divisor === 1 ? 0 : 2;
  const formatted = `$${(absolute / divisor).toFixed(digits)}${suffix}`;
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `-${formatted}`;
  return formatted;
}
