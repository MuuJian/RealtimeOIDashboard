export const OI_API_SCHEMA_VERSION = 7;

const ISO_TIMESTAMP_PATTERN = /^(\d{4})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:Z|[+-](?:0\d|1[0-4]):[0-5]\d)$/;
const DOMINANCE_SHARE_TOLERANCE = 0.01;
const MAX_RECENT_ERRORS = 10;
const NUMBER_MATCH_TOLERANCE = Number.EPSILON * 8;

const OPTIONAL_NUMBER_FIELDS = [
  "priceChangePercent",
  "price7dChangePercent",
  "fundingRatePercent",
  "oi24hChangePercent",
  "oi7dChangePercent",
];

const CVD_STATUSES = new Set([
  "buying",
  "selling",
  "neutral",
  "collecting",
  "untracked",
  "unavailable",
]);
const CVD_DIRECTIONS = new Set(["buying", "selling", "neutral"]);
const CVD_HEALTH = new Set([
  "warming",
  "live",
  "stale",
  "partial",
  "unavailable",
]);

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
    || !isCvdMeta(payload.cvd_meta)
    || !isOiDominanceHistory(payload.oi_dominance_history)
    || !payload.active_symbols.every(isSymbol)
    || !Array.isArray(payload.rows)
    || !Object.hasOwn(payload, "saved_at")
    || !isOptionalSavedAt(payload.saved_at)
    || !Object.hasOwn(payload, "error")
    || !isOptionalString(payload.error)
    || !isRecentErrors(payload.recent_errors)
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

function isCvdMeta(value) {
  if (!value || typeof value !== "object") return false;
  const counts = value.healthCounts;
  return ["warming", "live", "partial", "stale", "unavailable"].includes(
    value.serviceHealth,
  )
    && [
      value.universeSymbols,
      value.desiredShards,
      value.activeShards,
      value.connectedShards,
      value.backfillQueueSize,
    ].every(item => Number.isSafeInteger(item) && item >= 0)
    && isNonNegativeNumber(value.incomingMessagesPerSecond)
    && isNonNegativeNumber(value.processingLagMs)
    && counts
    && typeof counts === "object"
    && ["warming", "live", "stale", "partial", "unavailable"].every(
      key => Number.isSafeInteger(counts[key]) && counts[key] >= 0,
    );
}

function isOiDominanceHistory(value) {
  return Array.isArray(value)
    && value.length <= 200
    && value.every((point, index) => isOiDominancePoint(
      point,
      index === 0 ? null : value[index - 1],
    ));
}

function isOiDominancePoint(point, previousPoint) {
  if (
    !point
    || typeof point !== "object"
    || !isTimestamp(point.timestamp)
    || (previousPoint && point.timestamp <= previousPoint.timestamp)
  ) return false;
  const shares = [point.btc, point.eth, point.other];
  const values = [point.btcValue, point.ethValue, point.otherValue];
  if (
    !shares.every(share => isNonNegativeNumber(share) && share <= 100)
    || !values.every(isNonNegativeNumber)
  ) return false;
  const totalValue = values.reduce((sum, value) => sum + value, 0);
  return Number.isFinite(totalValue)
    && totalValue > 0
    && Math.abs(shares.reduce((sum, share) => sum + share, 0) - 100)
      < DOMINANCE_SHARE_TOLERANCE
    && shares.every((share, index) => (
      Math.abs(share - values[index] / totalValue * 100)
      < DOMINANCE_SHARE_TOLERANCE
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
    || !numbersNearlyEqual(item.currentOiValue, item.currentOi * item.price)
    || !Object.hasOwn(item, "volume24h")
    || !isOptionalNonNegativeNumber(item.volume24h)
    || !Object.hasOwn(item, "marketCap")
    || !isOptionalPositiveNumber(item.marketCap)
    || !isTimestamp(item.oiUpdatedAt)
    || !Object.hasOwn(item, "price7dBaseline")
    || !isOptionalPositiveNumber(item.price7dBaseline)
    || !Object.hasOwn(item, "nextFundingTime")
    || !isOptionalTimestamp(item.nextFundingTime)
    || (
      item.nextFundingTime !== null
      && item.nextFundingTime <= item.oiUpdatedAt
    )
  ) return false;

  if (!OPTIONAL_NUMBER_FIELDS.every(
    field => Object.hasOwn(item, field) && isOptionalNumber(item[field]),
  )) return false;

  if (!isConsistentPrice7dChange(item)) return false;

  if (!Object.hasOwn(item, "cvdStatus")) return true;
  return CVD_STATUSES.has(item.cvdStatus)
    && isOptionalNumber(item.cvd15m)
    && isOptionalNumber(item.cvd15mRatio)
    && isOptionalTimestamp(item.cvdUpdatedAt)
    && (!Object.hasOwn(item, "cvdDirection")
      || item.cvdDirection == null
      || CVD_DIRECTIONS.has(item.cvdDirection))
    && (!Object.hasOwn(item, "cvdHealth")
      || CVD_HEALTH.has(item.cvdHealth))
    && (!Object.hasOwn(item, "cvdAsOf") || isOptionalTimestamp(item.cvdAsOf))
    && (!Object.hasOwn(item, "cvdCoverageSeconds")
      || isOptionalNonNegativeNumber(item.cvdCoverageSeconds))
    && (!Object.hasOwn(item, "cvdReason")
      || item.cvdReason == null
      || typeof item.cvdReason === "string");
}

function isConsistentPrice7dChange(item) {
  if (item.price7dBaseline === null) {
    return item.price7dChangePercent === null;
  }
  if (!isFiniteNumber(item.price7dChangePercent)) return false;
  const expectedChange = (item.price - item.price7dBaseline)
    / item.price7dBaseline
    * 100;
  return numbersNearlyEqual(item.price7dChangePercent, expectedChange);
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

function isOptionalSavedAt(value) {
  if (value === null) return true;
  if (typeof value !== "string") return false;
  const match = ISO_TIMESTAMP_PATTERN.exec(value);
  if (!match || !Number.isFinite(Date.parse(value))) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const calendar = new Date(0);
  calendar.setUTCFullYear(year, month, 0);
  return day <= calendar.getUTCDate();
}

function isOptionalString(value) {
  return value === null || typeof value === "string";
}

function isRecentErrors(value) {
  return Array.isArray(value)
    && value.length <= MAX_RECENT_ERRORS
    && value.every(item => (
      item
      && typeof item === "object"
      && typeof item.symbol === "string"
      && item.symbol.length > 0
      && typeof item.error === "string"
    ));
}

function isTimestamp(value) {
  return Number.isSafeInteger(value) && value > 0;
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function numbersNearlyEqual(left, right) {
  if (!isFiniteNumber(left) || !isFiniteNumber(right)) return false;
  const scale = Math.max(1, Math.abs(left), Math.abs(right));
  return Math.abs(left - right) <= scale * NUMBER_MATCH_TOLERANCE;
}
