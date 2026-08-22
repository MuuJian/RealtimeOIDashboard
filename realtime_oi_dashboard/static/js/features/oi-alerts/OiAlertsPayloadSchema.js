export const OI_ALERTS_API_SCHEMA_VERSION = 2;

export function assertOiAlertsPayload(payload) {
  if (payload?.schema_version !== OI_ALERTS_API_SCHEMA_VERSION) {
    throw new Error("OI 警報前後端版本不一致，請重新整理頁面");
  }
  if (!isOiAlertsPayload(payload)) {
    throw new Error("OI 警報響應格式錯誤");
  }
  return payload;
}

export function isOiAlertsPayload(payload) {
  return Boolean(
    payload
    && payload.schema_version === OI_ALERTS_API_SCHEMA_VERSION
    && validConfig(payload.config)
    && validStatus(payload.telegram)
    && validStorage(payload.storage)
    && Array.isArray(payload.active)
    && payload.active.every(validActive)
    && Array.isArray(payload.events)
    && payload.events.length <= 50
    && payload.events.every(validEvent)
  );
}

function validConfig(config) {
  return Boolean(
    config
    && typeof config.enabled === "boolean"
    && typeof config.scale_alerts_enabled === "boolean"
    && Array.isArray(config.thresholds)
    && config.thresholds.length === 3
    && config.thresholds.every(positiveNumber)
    && config.thresholds[0] < config.thresholds[1]
    && config.thresholds[1] < config.thresholds[2]
    && Number.isSafeInteger(config.change_window_minutes)
    && config.change_window_minutes >= 1
    && config.change_window_minutes <= 240
    && positiveNumber(config.min_oi_change_percent)
    && nonNegativeNumber(config.min_price_change_percent)
    && typeof config.require_cvd_confirmation === "boolean"
    && Number.isSafeInteger(config.cooldown_minutes)
    && config.cooldown_minutes >= 0
    && config.cooldown_minutes <= 1440
    && Array.isArray(config.symbols)
    && config.symbols.every(symbol => /^[A-Z0-9]+USDT$/.test(symbol))
  );
}

function validStatus(status) {
  return Boolean(
    status
    && typeof status.status === "string"
    && optionalString(status.last_error)
    && optionalString(status.last_attempt_at)
  );
}

function validStorage(storage) {
  return Boolean(
    storage
    && ["ok", "load_error"].includes(storage.status)
    && optionalString(storage.last_error)
  );
}

function validActive(row) {
  return Boolean(
    row
    && /^[A-Z0-9]+USDT$/.test(row.symbol)
    && ["oi_scale", "oi_expansion"].includes(row.event_type)
    && positiveNumber(row.oi_value)
    && positiveNumber(row.threshold)
    && typeof row.signal === "string"
    && optionalNumber(row.oi_change_percent)
    && optionalNumber(row.price_change_percent)
    && typeof row.explanation === "string"
    && optionalString(row.as_of)
  );
}

function validEvent(row) {
  return Boolean(
    row
    && typeof row.event_id === "string"
    && row.event_id.length > 0
    && validActive({ ...row, as_of: row.triggered_at })
    && positiveNumber(row.threshold)
    && typeof row.triggered_at === "string"
    && ["pending", "queued", "sent", "failed", "not_configured"].includes(row.delivery_status)
    && optionalString(row.failure_reason)
    && optionalString(row.last_attempt_at)
    && (row.exchange_timestamp_ms === null || positiveNumber(row.exchange_timestamp_ms))
  );
}

function positiveNumber(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function nonNegativeNumber(value) {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function optionalNumber(value) {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function optionalString(value) {
  return value === null || (typeof value === "string" && value.trim().length > 0);
}
