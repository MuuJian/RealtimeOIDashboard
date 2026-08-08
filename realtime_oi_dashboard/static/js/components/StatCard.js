import { formatCurrency, formatPercent, formatPrice } from "../utils/format.js";

export function renderStatCards(elements, stats) {
  const changedValues = [];
  updateValue(
    elements.topIncrease,
    stats.topIncrease?.symbol || "-",
    changedValues,
  );
  elements.topIncreasePrice.textContent = formatPrice(stats.topIncrease?.price);
  elements.topIncreaseNote.textContent = formatPercent(stats.topIncrease?.priceChangePercent);
  elements.topIncreaseOiChange.textContent = formatPercent(
    stats.topIncrease?.oi24hChangePercent,
  );
  elements.topIncreaseOiValue.textContent = formatCurrency(
    stats.topIncrease?.currentOiValue,
  );
  updateValue(
    elements.topDecrease,
    stats.topDecrease?.symbol || "-",
    changedValues,
  );
  elements.topDecreasePrice.textContent = formatPrice(stats.topDecrease?.price);
  elements.topDecreaseNote.textContent = formatPercent(stats.topDecrease?.priceChangePercent);
  elements.topDecreaseOiChange.textContent = formatPercent(
    stats.topDecrease?.oi24hChangePercent,
  );
  elements.topDecreaseOiValue.textContent = formatCurrency(
    stats.topDecrease?.currentOiValue,
  );
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
  if (value === "實時") return "live";
  if (value === "異常") return "error";
  if (value === "暫停") return "paused";
  return "connecting";
}
