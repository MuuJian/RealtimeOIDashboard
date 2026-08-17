import {
  saveOiAlertsConfig,
  sendOiAlertsTestMessage,
} from "./OiAlertsApiClient.js";

const SIGNALS = ["建立多單", "加倉", "高 OI 警示"];
const SIGNAL_LABELS = new Map([
  ["Long entry", "建立多單"],
  ["Add position", "加倉"],
  ["High OI alert", "高 OI 警示"],
]);
const MILLION = 1_000_000;

export function createOiAlertsPanel({ elements }) {
  const {
    statusElement,
    signalLabelsElement,
    enabledInput,
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
  const configInputs = [enabledInput, ...thresholdInputs];
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
    signalLabelsElement.textContent = signalLabelsText(
      thresholdInputs.map(input => Number(input.value) * MILLION),
    );
    const editStatus = dirtyConfigInputs.size > 0 || focusedConfigInputs.size > 0
      ? "有尚未儲存的警報設定。"
      : "";
    statusElement.textContent = `${editStatus}${storageStatusText(payload.storage)} ${telegramStatusText(payload.telegram)}`;
    activeBody.replaceChildren(...rowsOrEmpty(sortRows(payload.active, activeSort), createActiveRow, 5));
    eventsBody.replaceChildren(...rowsOrEmpty(sortRows(payload.events, eventsSort), createEventRow, 8));
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
    return force
      || (!dirtyConfigInputs.has(input) && !focusedConfigInputs.has(input));
  }

  function setSaveControlsDisabled(disabled) {
    for (const control of [enabledInput, ...thresholdInputs, saveButton]) {
      if (control) control.disabled = disabled;
    }
  }

  return { bind, render, renderError };
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
  if (key === "oi_value" || key === "threshold") {
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
  return key === "oi_value" || key === "threshold" || key.endsWith("_at")
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
    formatUsd(row?.oi_value),
    formatUsd(row?.threshold),
    signalText(row?.signal),
    dateText(row?.last_triggered_at),
  ]);
}

function createEventRow(row) {
  return createRow([
    safeText(row?.symbol),
    formatUsd(row?.oi_value),
    formatUsd(row?.threshold),
    signalText(row?.signal),
    dateText(row?.triggered_at),
    deliveryStatusText(row?.delivery_status),
    failureReasonText(row?.failure_reason),
    dateText(row?.last_attempt_at),
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

function signalLabelsText(thresholds) {
  return SIGNALS.map((signal, index) => (
    `${formatThreshold(thresholds?.[index])}：${signal}`
  )).join(" | ");
}

function formatThreshold(value) {
  if (!Number.isFinite(value)) return "無法使用";
  return `${value / MILLION}M`;
}

function dateText(value) {
  return typeof value === "string" && value.trim() ? value : "無法使用";
}

function safeText(value, fallback = "無法使用") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function signalText(value) {
  return SIGNAL_LABELS.get(value) || safeText(value);
}

function deliveryStatusText(value) {
  return new Map([
    ["pending", "等待發送"],
    ["queued", "已加入佇列"],
    ["sent", "已發送"],
    ["failed", "發送失敗"],
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
