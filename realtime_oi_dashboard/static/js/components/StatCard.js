import { formatPercent } from "../utils/format.js";

export function renderStatCards(elements, stats) {
  const changedValues = [];
  updateValue(elements.changeCount, stats.changeCount, changedValues);
  updateValue(
    elements.topIncrease,
    stats.topIncrease?.symbol || "-",
    changedValues,
  );
  elements.topIncreaseNote.textContent = formatPercent(stats.topIncrease?.oi24hChangePercent);
  updateValue(
    elements.topDecrease,
    stats.topDecrease?.symbol || "-",
    changedValues,
  );
  elements.topDecreaseNote.textContent = formatPercent(stats.topDecrease?.oi24hChangePercent);
  return changedValues;
}

export function renderWsState(element, value) {
  if (element.textContent === value) return [];
  element.textContent = value;
  const metric = element.closest(".metric");
  if (metric) metric.dataset.connection = connectionState(value);
  return [element];
}

function updateValue(element, value, changedValues) {
  const text = String(value);
  if (element.textContent === text) return;
  element.textContent = text;
  changedValues.push(element);
}

function connectionState(value) {
  if (value === "实时") return "live";
  if (value === "异常") return "error";
  if (value === "暂停") return "paused";
  return "connecting";
}
