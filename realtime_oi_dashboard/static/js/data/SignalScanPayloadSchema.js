export const SIGNAL_SCAN_API_SCHEMA_VERSION = 1;

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
    && Array.isArray(payload.bulls)
    && Array.isArray(payload.bears)
    && Array.isArray(payload.spikes)
    && payload.bulls.every(isSignalRow)
    && payload.bears.every(isSignalRow)
    && payload.spikes.every(isSignalRow),
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
    && isFiniteNumber(item.volRatio),
  );
}

function isSymbol(value) {
  return typeof value === "string" && Boolean(value) && value === value.toUpperCase();
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}
