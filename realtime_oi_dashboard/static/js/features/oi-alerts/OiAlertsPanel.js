import {
  saveOiAlertsConfig,
  sendOiAlertsTestMessage,
} from "./OiAlertsApiClient.js";

const SIGNALS = ["Long entry", "Add position", "High OI alert"];
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

  function render(payload, { configSaved = false } = {}) {
    if (configSaved) dirtyConfigInputs.clear();
    renderConfig(payload.config, { force: configSaved });
    signalLabelsElement.textContent = signalLabelsText(
      thresholdInputs.map(input => Number(input.value) * MILLION),
    );
    const editStatus = dirtyConfigInputs.size > 0 || focusedConfigInputs.size > 0
      ? "Unsaved alert configuration. "
      : "";
    statusElement.textContent = `${editStatus}${storageStatusText(payload.storage)} ${telegramStatusText(payload.telegram)}`;
    activeBody.replaceChildren(...rowsOrEmpty(payload.active, createActiveRow, 5));
    eventsBody.replaceChildren(...rowsOrEmpty(payload.events, createEventRow, 8));
  }

  function renderError(error) {
    statusElement.textContent = error?.message || String(error);
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
      statusElement.textContent = "OI alert configuration saved";
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
        ? `Test message queued. ${telegramStatusText(result.telegram)}`
        : `Test message not queued. ${telegramStatusText(result.telegram)}`;
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

function rowsOrEmpty(rows, createRow, colspan) {
  if (!Array.isArray(rows) || rows.length === 0) {
    const tr = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = colspan;
    cell.textContent = "No alerts available";
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
    safeText(row?.signal),
    dateText(row?.last_triggered_at),
  ]);
}

function createEventRow(row) {
  return createRow([
    safeText(row?.symbol),
    formatUsd(row?.oi_value),
    formatUsd(row?.threshold),
    safeText(row?.signal),
    dateText(row?.triggered_at),
    safeText(row?.delivery_status),
    safeText(row?.failure_reason, "none"),
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
  const status = safeText(telegram?.status, "unavailable");
  const lastError = typeof telegram?.last_error === "string" && telegram.last_error
    ? `; last error: ${telegram.last_error}`
    : "";
  return `Telegram: ${status}${lastError}; last attempt ${dateText(telegram?.last_attempt_at)}`;
}

function storageStatusText(storage) {
  const status = safeText(storage?.status, "unavailable");
  const lastError = typeof storage?.last_error === "string" && storage.last_error
    ? `; error: ${storage.last_error}`
    : "";
  return `Alert state: ${status}${lastError}.`;
}

function formatUsd(value) {
  if (!Number.isFinite(value)) return "unavailable";
  return `$${(value / MILLION).toLocaleString(undefined, {
    maximumFractionDigits: 2,
  })}M`;
}

function signalLabelsText(thresholds) {
  return SIGNALS.map((signal, index) => (
    `${formatThreshold(thresholds?.[index])}: ${signal}`
  )).join(" | ");
}

function formatThreshold(value) {
  if (!Number.isFinite(value)) return "unavailable";
  return `${value / MILLION}M`;
}

function dateText(value) {
  return typeof value === "string" && value.trim() ? value : "unavailable";
}

function safeText(value, fallback = "unavailable") {
  return typeof value === "string" && value.trim() ? value : fallback;
}
