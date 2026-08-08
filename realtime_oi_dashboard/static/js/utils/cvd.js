const STATUS_LABELS = {
  buying: "買盤主導",
  selling: "賣盤主導",
  neutral: "中性",
  collecting: "資料累積中",
  untracked: "未追蹤",
  unavailable: "資料不可用",
};

export function formatCvd(_value, ratio) {
  if (!Number.isFinite(ratio)) return "-";
  const ratioPercent = ratio * 100;
  return `${ratioPercent >= 0 ? "+" : ""}${ratioPercent.toFixed(1)}%`;
}

export function cvdStatusLabel(status) {
  return STATUS_LABELS[status] || STATUS_LABELS.unavailable;
}
