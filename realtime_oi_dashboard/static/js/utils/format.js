export function formatCurrency(value) {
  const number = finiteNumber(value);
  if (number == null) return "-";
  if (Math.abs(number) >= 100000000) return "$" + (number / 100000000).toFixed(2) + "亿";
  if (Math.abs(number) >= 10000) return "$" + (number / 10000).toFixed(2) + "万";
  return "$" + number.toFixed(0);
}

export function formatPrice(value) {
  const number = finiteNumber(value);
  if (number == null) return "-";
  return "$" + number.toLocaleString(undefined, {
    maximumSignificantDigits: 6,
    useGrouping: Math.abs(number) >= 1000,
  });
}

export function formatPercent(value) {
  const number = finiteNumber(value);
  if (number == null) return "-";
  return (number >= 0 ? "+" : "") + number.toFixed(2) + "%";
}

export function formatFundingRate(value) {
  const number = finiteNumber(value);
  if (number == null) return "-";
  return (number >= 0 ? "+" : "") + number.toFixed(4) + "%";
}

export function signClass(value) {
  const number = finiteNumber(value);
  if (number == null) return "neutral";
  if (number > 0) return "pos";
  if (number < 0) return "neg";
  return "neutral";
}

export function heatStyle(value, max) {
  const number = finiteNumber(value);
  const maximum = finiteNumber(max);
  if (number == null || number === 0 || maximum == null || maximum <= 0) return "";
  const ratio = Math.min(Math.abs(number) / maximum, 1);
  const alpha = 0.08 + ratio * 0.22;
  const color = number >= 0 ? "var(--green)" : "var(--red)";
  return `background: rgba(${color}, ${alpha});`;
}

export function formatFundingTitle(nextFundingTime) {
  const time = finiteNumber(nextFundingTime);
  if (time == null || time <= Date.now()) return "";
  const date = new Date(time);
  if (Number.isNaN(date.getTime())) return "";
  return `下次资金费结算: ${date.toLocaleString()}`;
}

export function formatOiUpdateAge(value, now = Date.now()) {
  const time = finiteNumber(value);
  if (time == null || time <= 0) return "-";

  const ageMs = Math.max(0, now - time);
  if (ageMs < 5000) return "刚刚";
  if (ageMs < 60000) return `${Math.floor(ageMs / 1000)}秒前`;
  return `${Math.floor(ageMs / 60000)}分钟前`;
}

export function oiUpdateSignalState(value, now = Date.now()) {
  const time = finiteNumber(value);
  if (time == null || time <= 0) return "danger";

  const ageMs = Math.max(0, now - time);
  if (ageMs >= 60 * 1000) return "danger";
  if (ageMs > 20 * 1000) return "warning";
  return "fresh";
}

export function formatOiUpdateTitle(value) {
  const time = finiteNumber(value);
  if (time == null || time <= 0) return "";
  const date = new Date(time);
  if (Number.isNaN(date.getTime())) return "";
  return `OI 获取时间：${date.toLocaleString()}`;
}

export function coinGlassUrl(symbol) {
  return `https://www.coinglass.com/tv/zh/Binance_${encodeURIComponent(symbol)}`;
}

export function binanceFuturesUrl(symbol) {
  return `https://www.binance.com/zh-CN/futures/${encodeURIComponent(symbol)}`;
}

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
