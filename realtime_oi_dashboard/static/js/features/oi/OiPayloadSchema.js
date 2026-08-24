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
    throw new Error("前後端版本不一致，請重新整理頁面或重啟服務");
  }
  if (!isOiPayload(payload)) {
    throw new Error("OI 響應格式錯誤");
  }
  return payload;
}

export function isOiPayload(payload) {
  if (
    !payload
    || !Array.isArray(payload.active_symbols)
    || !Number.isSafeInteger(payload.total_symbols)
    || payload.total_symbols !== payload.active_symbols.length
    || !Number.isSafeInteger(payload.market_cap_loaded_symbols)
    || payload.market_cap_loaded_symbols < 0
    || payload.market_cap_loaded_symbols > payload.total_symbols
    || !isOiDominanceHistory(payload.oi_dominance_history)
    || !payload.active_symbols.every(isSymbol)
    || !Array.isArray(payload.rows)
  ) return false;

  const activeSymbols = new Set(payload.active_symbols);
  if (activeSymbols.size !== payload.active_symbols.length) return false;

  const rowSymbols = new Set();
  for (const row of payload.rows) {
    if (
      !isOiRow(row)
      || !activeSymbols.has(row.symbol)
      || rowSymbols.has(row.symbol)
    ) return false;
    rowSymbols.add(row.symbol);
  }
  return true;
}

function isOiDominanceHistory(value) {
  return Array.isArray(value)
    && value.length <= 200
    && value.every((point, index) => (
      point
      && typeof point === "object"
      && isTimestamp(point.timestamp)
      && (index === 0 || point.timestamp > value[index - 1].timestamp)
      && [point.btc, point.eth, point.other].every(
        share => isNonNegativeNumber(share) && share <= 100,
      )
      && [point.btcValue, point.ethValue, point.otherValue]
        .every(isNonNegativeNumber)
      && Math.abs(
        point.btc + point.eth + point.other - 100
      ) < 0.01
    ));
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
    && /^[A-Z0-9]+$/.test(value);
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
