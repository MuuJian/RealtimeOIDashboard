import {
  saveOiAlertsConfig,
  sendOiAlertsTestMessage,
} from "./OiAlertsApiClient.js";
import { formatUtc8DateTime } from "../../utils/format.js";

const SIGNALS = ["OI 規模提醒", "大額 OI", "超大額 OI"];
const SIGNAL_LABELS = new Map([
  ["OI scale alert", "OI 規模提醒"],
  ["Large OI alert", "大額 OI"],
  ["Very large OI alert", "超大額 OI"],
  ["Bullish OI expansion", "多頭擴倉"],
  ["Bearish OI expansion", "空頭擴倉"],
  ["OI expansion", "OI 擴張／方向未確認"],
  ["Long entry", "舊版：建立多單"],
  ["Add position", "舊版：加倉"],
  ["High OI alert", "舊版：高 OI 警示"],
]);
const MILLION = 1_000_000;

export function createOiAlertsPanel({ elements }) {
  const {
    statusElement,
    signalLabelsElement,
    enabledInput,
    scaleEnabledInput,
    symbolsInput,
    windowMinutesInput,
    minOiChangeInput,
    minPriceChangeInput,
    cooldownMinutesInput,
    requireCvdInput,
    threshold75Input,
    threshold100Input,
    threshold150Input,
    saveButton,
    testButton,
    activeBody,
    eventsBody,
    activeSortButtons = [],
    eventsSortButtons = [],
  } = elements;
  const thresholdInputs = [
    threshold75Input,
    threshold100Input,
    threshold150Input,
  ];
  const configInputs = [
    enabledInput,
    scaleEnabledInput,
    symbolsInput,
    windowMinutesInput,
    minOiChangeInput,
    minPriceChangeInput,
    cooldownMinutesInput,
    requireCvdInput,
    ...thresholdInputs,
  ];
  let savePending = false;
  let testPending = false;
  const dirtyConfigInputs = new Set();
  const focusedConfigInputs = new Set();
  let activeSort = null;
  let eventsSort = null;
  let lastPayload = null;

  function render(payload, { configSaved = false } = {}) {
    lastPayload = payload;
    if (configSaved) dirtyConfigInputs.clear();
    renderConfig(payload.config, { force: configSaved });
    signalLabelsElement.textContent = signalLabelsText({
      thresholds: thresholdInputs.map(input => Number(input.value) * MILLION),
      windowMinutes: Number(windowMinutesInput?.value || 15),
      minOiChange: Number(minOiChangeInput?.value || 3),
      minPriceChange: Number(minPriceChangeInput?.value || 0.5),
    });
    const editStatus = dirtyConfigInputs.size > 0 || focusedConfigInputs.size > 0
      ? "有尚未儲存的警報設定。"
      : "";
    statusElement.textContent = `${editStatus}${storageStatusText(payload.storage)} ${telegramStatusText(payload.telegram)}`;
    activeBody.replaceChildren(...rowsOrEmpty(sortRows(payload.active, activeSort), createActiveRow, 8));
    eventsBody.replaceChildren(...rowsOrEmpty(sortRows(payload.events, eventsSort), createEventRow, 9));
  }

  function renderError(error) {
    statusElement.textContent = "無法更新 OI 警報。請稍後再試。";
  }

  function bind(signal) {
    for (const input of configInputs) {
      input?.addEventListener("input", () => {
        dirtyConfigInputs.add(input);
      }, { signal });
      input?.addEventListener("change", () => {
        dirtyConfigInputs.add(input);
      }, { signal });
      input?.addEventListener("focus", () => {
        focusedConfigInputs.add(input);
      }, { signal });
      input?.addEventListener("blur", () => {
        focusedConfigInputs.delete(input);
      }, { signal });
    }
    bindSortButtons(activeSortButtons, "active", signal);
    bindSortButtons(eventsSortButtons, "events", signal);
    saveButton?.addEventListener("click", event => {
      event?.preventDefault?.();
      void saveConfig();
    }, { signal });
    testButton?.addEventListener("click", event => {
      event?.preventDefault?.();
      void sendTestMessage();
    }, { signal });
  }

  async function saveConfig() {
    if (savePending) return;
    savePending = true;
    setSaveControlsDisabled(true);
    try {
      const payload = await saveOiAlertsConfig({
        enabled: Boolean(enabledInput.checked),
        scale_alerts_enabled: scaleEnabledInput ? Boolean(scaleEnabledInput.checked) : true,
        change_window_minutes: Number(windowMinutesInput?.value || 15),
        min_oi_change_percent: Number(minOiChangeInput?.value || 3),
        min_price_change_percent: Number(minPriceChangeInput?.value || 0.5),
        require_cvd_confirmation: Boolean(requireCvdInput?.checked),
        cooldown_minutes: Number(cooldownMinutesInput?.value || 30),
        symbols: parseSymbols(symbolsInput?.value),
        thresholds: thresholdInputs.map(input => Number(input.value) * MILLION),
      });
      render(payload, { configSaved: true });
      statusElement.textContent = "OI 警報設定已儲存。";
    } catch (error) {
      renderError(error);
    } finally {
      savePending = false;
      setSaveControlsDisabled(false);
    }
  }

  async function sendTestMessage() {
    if (testPending) return;
    testPending = true;
    if (testButton) testButton.disabled = true;
    try {
      const result = await sendOiAlertsTestMessage();
      statusElement.textContent = result.queued
        ? `測試訊息已加入佇列。${telegramStatusText(result.telegram)}`
        : `測試訊息未加入佇列。${telegramStatusText(result.telegram)}`;
    } catch (error) {
      renderError(error);
    } finally {
      testPending = false;
      if (testButton) testButton.disabled = false;
    }
  }

  function renderConfig(config, { force = false } = {}) {
    if (canRenderConfigInput(enabledInput, force)) {
      enabledInput.checked = Boolean(config?.enabled);
    }
    if (canRenderConfigInput(scaleEnabledInput, force)) {
      scaleEnabledInput.checked = Boolean(config?.scale_alerts_enabled);
    }
    if (canRenderConfigInput(requireCvdInput, force)) {
      requireCvdInput.checked = Boolean(config?.require_cvd_confirmation);
    }
    if (canRenderConfigInput(symbolsInput, force)) {
      symbolsInput.value = Array.isArray(config?.symbols) ? config.symbols.join(", ") : "";
    }
    for (const [input, value] of [
      [windowMinutesInput, config?.change_window_minutes],
      [minOiChangeInput, config?.min_oi_change_percent],
      [minPriceChangeInput, config?.min_price_change_percent],
      [cooldownMinutesInput, config?.cooldown_minutes],
    ]) {
      if (canRenderConfigInput(input, force)) input.value = value ?? "";
    }
    const thresholds = Array.isArray(config?.thresholds) ? config.thresholds : [];
    thresholdInputs.forEach((input, index) => {
      if (!canRenderConfigInput(input, force)) return;
      const value = thresholds[index];
      input.value = Number.isFinite(value) ? String(value / MILLION) : "";
    });
  }

  function bindSortButtons(buttons, table, signal) {
    for (const button of buttons) {
      button?.addEventListener("click", () => {
        const currentSort = table === "active" ? activeSort : eventsSort;
        const key = button.dataset?.sortKey;
        if (!key) return;
        const direction = currentSort?.key === key
          ? (currentSort.direction === "asc" ? "desc" : "asc")
          : defaultSortDirection(key);
        const nextSort = { key, direction };
        if (table === "active") activeSort = nextSort;
        else eventsSort = nextSort;
        updateSortButtons(buttons, nextSort);
        renderLastPayload();
      }, { signal });
    }
  }

  function renderLastPayload() {
    if (lastPayload) render(lastPayload);
  }

  function canRenderConfigInput(input, force) {
    return Boolean(input) && (force
      || (!dirtyConfigInputs.has(input) && !focusedConfigInputs.has(input))
    );
  }

  function setSaveControlsDisabled(disabled) {
    for (const control of [...configInputs, saveButton]) {
      if (control) control.disabled = disabled;
    }
  }

  function addSymbol(symbol) {
    if (!symbolsInput) return;
    const symbols = parseSymbols(symbolsInput.value);
    if (!symbols.includes(symbol)) symbols.push(symbol);
    symbolsInput.value = symbols.join(", ");
    dirtyConfigInputs.add(symbolsInput);
    symbolsInput.focus?.();
    statusElement.textContent = `${symbol} 已加入監控清單；請儲存規則。`;
  }

  return { addSymbol, bind, render, renderError };
}

function sortRows(rows, sort) {
  if (!Array.isArray(rows) || !sort) return rows;
  const multiplier = sort.direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => multiplier * compareSortValues(
    left?.[sort.key],
    right?.[sort.key],
    sort.key,
  ));
}

function compareSortValues(left, right, key) {
  if (["oi_value", "threshold", "oi_change_percent", "price_change_percent"].includes(key)) {
    return compareNumbers(left, right);
  }
  if (key.endsWith("_at")) {
    return compareNumbers(Date.parse(left) || 0, Date.parse(right) || 0);
  }
  return safeText(left, "").localeCompare(safeText(right, ""), "zh-Hant");
}

function compareNumbers(left, right) {
  const leftValue = Number.isFinite(left) ? left : Number.NEGATIVE_INFINITY;
  const rightValue = Number.isFinite(right) ? right : Number.NEGATIVE_INFINITY;
  return leftValue - rightValue;
}

function defaultSortDirection(key) {
  return ["oi_value", "threshold", "oi_change_percent", "price_change_percent"].includes(key) || key.endsWith("_at") || key === "as_of"
    ? "desc"
    : "asc";
}

function updateSortButtons(buttons, sort) {
  for (const button of buttons) {
    const selected = button?.dataset?.sortKey === sort.key;
    if (button?.dataset) button.dataset.sortDirection = selected ? sort.direction : "";
    button?.setAttribute?.("aria-pressed", selected ? "true" : "false");
    const header = button?.parentElement || button?.parentNode;
    header?.setAttribute?.("aria-sort", selected
      ? (sort.direction === "asc" ? "ascending" : "descending")
      : "none");
  }
}

function rowsOrEmpty(rows, createRow, colspan) {
  if (!Array.isArray(rows) || rows.length === 0) {
    const tr = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = colspan;
    cell.textContent = "目前沒有警報資料";
    tr.append(cell);
    return [tr];
  }
  return rows.map(createRow);
}

function createActiveRow(row) {
  return createRow([
    safeText(row?.symbol),
    eventTypeText(row?.event_type),
    formatUsd(row?.oi_value),
    formatPercentValue(row?.oi_change_percent),
    formatPercentValue(row?.price_change_percent),
    signalText(row?.signal),
    explanationText(row),
    dateText(row?.as_of),
  ]);
}

function explanationText(row) {
  if (row?.event_type === "oi_scale" && Number.isFinite(row?.threshold)) {
    return `${signalText(row.signal)}：目前 OI ${formatUsd(row.oi_value)}，門檻 ${formatUsd(row.threshold)}`;
  }
  if (row?.event_type === "oi_expansion") {
    const parts = [
      `OI ${formatPercentValue(row.oi_change_percent)}`,
      `價格 ${formatPercentValue(row.price_change_percent)}`,
    ];
    return `${signalText(row.signal)}：${parts.join("、")}`;
  }
  return safeText(row?.explanation);
}

function createEventRow(row) {
  return createRow([
    dateText(row?.triggered_at),
    safeText(row?.symbol),
    eventTypeText(row?.event_type),
    formatUsd(row?.oi_value),
    formatPercentValue(row?.oi_change_percent),
    formatPercentValue(row?.price_change_percent),
    signalText(row?.signal),
    deliveryStatusText(row?.delivery_status),
    failureReasonText(row?.failure_reason),
  ]);
}

function createRow(values) {
  const tr = document.createElement("tr");
  for (const value of values) {
    const cell = document.createElement("td");
    cell.textContent = value;
    tr.append(cell);
  }
  return tr;
}

function telegramStatusText(telegram) {
  const status = telegramStatusLabel(telegram?.status);
  return `Telegram：${status}；最近嘗試：${dateText(telegram?.last_attempt_at)}。`;
}

function storageStatusText(storage) {
  const status = storageStatusLabel(storage?.status);
  return `警報狀態：${status}。`;
}

function formatUsd(value) {
  if (!Number.isFinite(value)) return "無法使用";
  return `$${(value / MILLION).toLocaleString(undefined, {
    maximumFractionDigits: 2,
  })}M`;
}

function signalLabelsText({ thresholds, windowMinutes, minOiChange, minPriceChange }) {
  const scale = SIGNALS.map((signal, index) => (
    `${formatThreshold(thresholds?.[index])}：${signal}`
  )).join(" | ");
  return `${windowMinutes}m OI ≥ ${minOiChange}% 且價格 ≥ ±${minPriceChange}%：方向擴倉；${scale}`;
}

function formatThreshold(value) {
  if (!Number.isFinite(value)) return "無法使用";
  return `${value / MILLION}M`;
}

function dateText(value) {
  if (typeof value !== "string" || !value.trim()) return "-";
  return formatUtc8DateTime(value) || value;
}

function safeText(value, fallback = "無法使用") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function signalText(value) {
  return SIGNAL_LABELS.get(value) || safeText(value);
}

function eventTypeText(value) {
  return new Map([
    ["oi_expansion", "方向訊號"],
    ["oi_scale", "OI 規模"],
  ]).get(value) || safeText(value);
}

function formatPercentValue(value) {
  if (!Number.isFinite(value)) return "-";
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function parseSymbols(value) {
  const symbols = String(value || "")
    .split(/[\s,，]+/)
    .map(symbol => symbol.trim().toUpperCase())
    .filter(Boolean);
  return [...new Set(symbols)];
}


function deliveryStatusText(value) {
  return new Map([
    ["pending", "等待發送"],
    ["queued", "已加入佇列"],
    ["sent", "已發送"],
    ["failed", "發送失敗"],
    ["not_configured", "Telegram 未設定"],
  ]).get(value) || safeText(value);
}

function failureReasonText(value) {
  return new Map([
    ["Telegram delivery failed", "Telegram 發送失敗"],
    ["delivery queue is full", "通知佇列已滿"],
  ]).get(value) || "無";
}

function telegramStatusLabel(value) {
  return new Map([
    ["configured", "已設定"],
    ["not_configured", "尚未設定"],
    ["sending", "傳送中"],
    ["queued", "已加入佇列"],
    ["sent", "已發送"],
    ["failed", "發送失敗"],
  ]).get(value) || "無法使用";
}

function storageStatusLabel(value) {
  return new Map([
    ["ok", "正常"],
    ["load_error", "讀取失敗"],
  ]).get(value) || "無法使用";
}
