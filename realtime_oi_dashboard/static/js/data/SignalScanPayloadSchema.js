export const SIGNAL_SCAN_API_SCHEMA_VERSION = 2;

const ISO_TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})$/;
const MAX_TREND_ROWS = 8;
const MAX_SPIKE_ROWS = 10;
const MAX_RECENT_ERRORS = 10;
const MAX_RECENT_ERROR_TEXT_LENGTH = 512;

export function assertSignalScanPayload(payload) {
  if (payload?.schema_version !== SIGNAL_SCAN_API_SCHEMA_VERSION) {
    throw new Error("前后端版本不一致，请刷新页面或重启服务");
  }
  if (!isSignalScanPayload(payload)) {
    throw new Error("訊號掃描响应格式错误");
  }
  return payload;
}

export function isSignalScanPayload(payload) {
  return Boolean(
    payload
    && payload.schema_version === SIGNAL_SCAN_API_SCHEMA_VERSION
    && Array.isArray(payload.bulls)
    && Array.isArray(payload.bears)
    && Array.isArray(payload.spikes)
    && payload.bulls.length <= MAX_TREND_ROWS
    && payload.bears.length <= MAX_TREND_ROWS
    && payload.spikes.length <= MAX_SPIKE_ROWS
    && isOptionalTimestamp(payload.saved_at)
    && isOptionalString(payload.error)
    && isScanCoverage(payload)
    && Array.isArray(payload.recent_errors)
    && payload.recent_errors.length <= MAX_RECENT_ERRORS
    && payload.recent_errors.every(isRecentError)
    && payload.bulls.every(isSignalRow)
    && payload.bears.every(isSignalRow)
    && payload.spikes.every(isSignalRow)
    && hasUniqueSymbols(payload.bulls)
    && hasUniqueSymbols(payload.bears)
    && hasUniqueSymbols(payload.spikes)
    && isErrorStateConsistent(payload),
  );
}

function isSignalRow(item) {
  return Boolean(
    item
    && typeof item === "object"
    && isSymbol(item.symbol)
    && isFiniteNumber(item.price)
    && isFiniteNumber(item.chg1h)
    && isFiniteNumber(item.chg24h)
    && isFiniteNumber(item.aboveE20)
    && isFiniteNumber(item.volRatio)
    && typeof item.isBull === "boolean"
    && typeof item.isBear === "boolean"
    && !(item.isBull && item.isBear)
    && item.price > 0
    && item.volRatio >= 0,
  );
}

function isSymbol(value) {
  return typeof value === "string"
    && value === value.trim()
    && /^[A-Z0-9]+USDT$/.test(value);
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function isOptionalString(value) {
  return value === null
    || (typeof value === "string" && value.trim().length > 0);
}

function isOptionalTimestamp(value) {
  return value === null || isTimestamp(value);
}

function isScanCoverage(payload) {
  if (
    !Number.isSafeInteger(payload.scan_total)
    || !Number.isSafeInteger(payload.scan_succeeded)
    || payload.scan_total < 0
    || payload.scan_succeeded < 0
    || payload.scan_succeeded > payload.scan_total
    || typeof payload.partial !== "boolean"
  ) return false;
  if (payload.partial) {
    if (
      payload.scan_total <= 0
      || payload.scan_succeeded >= payload.scan_total
    ) return false;
    if (payload.scan_succeeded === 0) {
      return payload.error !== null && isOptionalTimestamp(payload.saved_at);
    }
    return isTimestamp(payload.saved_at);
  }
  return (
    payload.scan_succeeded === payload.scan_total
    && (payload.scan_total === 0 || isTimestamp(payload.saved_at))
  );
}

function hasUniqueSymbols(rows) {
  const symbols = new Set();
  return rows.every(row => {
    if (symbols.has(row.symbol)) return false;
    symbols.add(row.symbol);
    return true;
  });
}

function isErrorStateConsistent(payload) {
  if (payload.error === null) return true;
  return (
    payload.bulls.length === 0
    && payload.bears.length === 0
    && payload.spikes.length === 0
  );
}

function isRecentError(item) {
  return Boolean(
    item
    && isSymbol(item.symbol)
    && typeof item.error === "string"
    && item.error.trim().length > 0
    && hasAtMostCodePoints(item.error, MAX_RECENT_ERROR_TEXT_LENGTH),
  );
}

function hasAtMostCodePoints(value, maximum) {
  let count = 0;
  for (const _character of value) {
    count += 1;
    if (count > maximum) return false;
  }
  return true;
}

function isTimestamp(value) {
  if (typeof value !== "string") return false;
  const match = ISO_TIMESTAMP_PATTERN.exec(value);
  if (!match) return false;
  const [
    , yearText,
    monthText,
    dayText,
    hourText,
    minuteText,
    secondText,
    zone,
  ] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText);
  const daysInMonth = [
    31,
    isLeapYear(year) ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  if (
    month < 1
    || month > 12
    || day < 1
    || day > daysInMonth[month - 1]
    || hour > 23
    || minute > 59
    || second > 59
  ) return false;
  if (zone !== "Z") {
    const offsetHours = Number(zone.slice(1, 3));
    const offsetMinutes = Number(zone.slice(4, 6));
    if (offsetHours > 23 || offsetMinutes > 59) return false;
  }
  return Number.isFinite(Date.parse(value));
}

function isLeapYear(year) {
  return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
}
