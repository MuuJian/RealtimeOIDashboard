export const OI_API_SCHEMA_VERSION = 7;

const OPTIONAL_NUMBER_FIELDS = [
  "priceChangePercent",
  "price7dChangePercent",
  "fundingRatePercent",
  "oi24hChangePercent",
  "oi7dChangePercent",
  "marketCap",
];

export function assertOiPayload(payload) {
  if (payload?.schema_version !== OI_API_SCHEMA_VERSION) {
    throw new Error("前后端版本不一致，请刷新页面或重启服务");
  }
  if (!isOiPayload(payload)) {
    throw new Error("OI 响应格式错误");
  }
  return payload;
}

export function isOiPayload(payload) {
  return Boolean(
    payload
    && Array.isArray(payload.active_symbols)
    && Number.isSafeInteger(payload.total_symbols)
    && payload.total_symbols === payload.active_symbols.length
    && Number.isSafeInteger(payload.market_cap_loaded_symbols)
    && payload.market_cap_loaded_symbols >= 0
    && payload.market_cap_loaded_symbols <= payload.total_symbols
    && payload.active_symbols.every(isSymbol)
    && Array.isArray(payload.rows)
    && payload.rows.every(isOiRow),
  );
}

export function isOiRow(item) {
  if (
    !item
    || typeof item !== "object"
    || !isSymbol(item.symbol)
    || !isPositiveNumber(item.price)
    || !isNonNegativeNumber(item.currentOi)
    || !isNonNegativeNumber(item.currentOiValue)
    || !isOptionalNonNegativeNumber(item.volume24h)
    || !isTimestamp(item.oiUpdatedAt)
    || !Object.hasOwn(item, "price7dBaseline")
    || !isOptionalPositiveNumber(item.price7dBaseline)
    || !isOptionalTimestamp(item.nextFundingTime)
  ) return false;

  return OPTIONAL_NUMBER_FIELDS.every(
    field => Object.hasOwn(item, field) && isOptionalNumber(item[field]),
  );
}

function isSymbol(value) {
  return typeof value === "string"
    && Boolean(value)
    && value === value.trim()
    && value === value.toUpperCase();
}

function isPositiveNumber(value) {
  return isFiniteNumber(value) && value > 0;
}

function isNonNegativeNumber(value) {
  return isFiniteNumber(value) && value >= 0;
}

function isOptionalNumber(value) {
  return value == null || isFiniteNumber(value);
}

function isOptionalNonNegativeNumber(value) {
  return value == null || isNonNegativeNumber(value);
}

function isOptionalPositiveNumber(value) {
  return value == null || isPositiveNumber(value);
}

function isOptionalTimestamp(value) {
  return value == null || isTimestamp(value);
}

function isTimestamp(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}
