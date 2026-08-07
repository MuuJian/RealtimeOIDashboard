const STATUS_LABELS = {
  buying: "買盤主導",
  selling: "賣盤主導",
  neutral: "中性",
  collecting: "資料累積中",
  untracked: "未追蹤",
  unavailable: "資料不可用",
};

export function formatCvd(value, ratio) {
  if (!Number.isFinite(value) || !Number.isFinite(ratio)) return "-";
  const sign = value >= 0 ? "+" : "-";
  const absolute = Math.abs(value);
  const amount = absolute >= 1_000_000
    ? `$${(absolute / 1_000_000).toFixed(2)}M`
    : absolute >= 1_000
      ? `$${(absolute / 1_000).toFixed(2)}K`
      : `$${absolute.toFixed(0)}`;
  const ratioPercent = ratio * 100;
  return `${sign}${amount} · ${ratioPercent >= 0 ? "+" : ""}${ratioPercent.toFixed(1)}%`;
}

export function cvdStatusLabel(status) {
  return STATUS_LABELS[status] || STATUS_LABELS.unavailable;
}
