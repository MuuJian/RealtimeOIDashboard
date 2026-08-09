export function formatCurrency(value) {
  const number = finiteNumber(value);
  if (number == null) return "-";
  if (Math.abs(number) >= 1000000000000) return "$" + (number / 1000000000000).toFixed(2) + "兆";
  if (Math.abs(number) >= 100000000) return "$" + (number / 100000000).toFixed(2) + "億";
  if (Math.abs(number) >= 10000) return "$" + (number / 10000).toFixed(2) + "萬";
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

export function formatRatioPercent(value) {
  const number = finiteNumber(value);
  if (number == null || number < 0) return "-";
  return (number * 100).toFixed(2) + "%";
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
  const formatted = formatUtc8DateTime(time);
  return formatted ? `下次資金費結算: ${formatted}` : "";
}

export function formatOiUpdateAge(value, now = Date.now()) {
  const time = finiteNumber(value);
  if (time == null || time <= 0) return "-";

  const ageMs = Math.max(0, now - time);
  if (ageMs < 5000) return "剛剛";
  if (ageMs < 60000) return `${Math.floor(ageMs / 1000)}秒前`;
  return `${Math.floor(ageMs / 60000)}分鐘前`;
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
  const formatted = formatUtc8DateTime(time);
  return formatted ? `OI 獲取時間：${formatted}` : "";
}

export function formatUtc8DateTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return "";

  const shifted = new Date(date.getTime() + 8 * 60 * 60 * 1000);
  const datePart = [
    shifted.getUTCFullYear(),
    twoDigits(shifted.getUTCMonth() + 1),
    twoDigits(shifted.getUTCDate()),
  ].join("-");
  const timePart = [
    twoDigits(shifted.getUTCHours()),
    twoDigits(shifted.getUTCMinutes()),
    twoDigits(shifted.getUTCSeconds()),
  ].join(":");
  return `${datePart} ${timePart} +08:00`;
}

const TRADINGVIEW_SYMBOL_MAP = {
  "币安人生USDT": "BIANRENSHENGUSDT",
  "龙虾USDT": "LONGXIAUSDT",
  "我踏马来了USDT": "WOTAMALAILIAOUSDT",
};

export function tradingViewUrl(symbol) {
  const tradingViewSymbol = TRADINGVIEW_SYMBOL_MAP[symbol] || symbol;
  return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent(
    `BINANCE:${tradingViewSymbol}.P`,
  )}`;
}

export function binanceFuturesUrl(symbol) {
  return `https://www.binance.com/zh-CN/futures/${encodeURIComponent(symbol)}`;
}

function finiteNumber(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function twoDigits(value) {
  return String(value).padStart(2, "0");
}
