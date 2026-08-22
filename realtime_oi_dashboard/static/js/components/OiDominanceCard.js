import { formatCurrency } from "../utils/format.js";
import { buildOiDominance } from "../utils/oiDominance.js";

export function renderOiDominance(elements, rows) {
  const dominance = buildOiDominance(rows);
  const segments = keyedElements(elements.oiDominanceSegments);
  const items = keyedElements(elements.oiDominanceItems);
  const changedValues = [];

  for (const group of dominance.groups) {
    const segment = segments.get(group.key);
    if (segment) {
      segment.style.width = `${group.percent}%`;
      segment.title = dominance.total > 0
        ? `${group.label}：${formatShare(group.percent)} · ${formatCurrency(group.value)}`
        : "暫無資料";
    }

    const item = items.get(group.key);
    if (!item) continue;
    updateText(
      item.querySelector("[data-oi-dominance-percent]"),
      dominance.total > 0 ? formatShare(group.percent) : "-",
      changedValues,
    );
    updateText(
      item.querySelector("[data-oi-dominance-value]"),
      dominance.total > 0 ? formatCurrency(group.value) : "-",
      changedValues,
    );
  }

  if (elements.oiDominanceBar) {
    elements.oiDominanceBar.setAttribute(
      "aria-label",
      dominance.total > 0
        ? dominance.groups
          .map(group => `${group.label} ${formatShare(group.percent)}`)
          .join("，")
        : "OI 市場佔比暫無資料",
    );
  }

  return changedValues;
}

function keyedElements(elements) {
  return new Map([...elements].map(element => [
    element.dataset.oiDominanceSegment || element.dataset.oiDominanceItem,
    element,
  ]));
}

function formatShare(value) {
  return `${value.toFixed(1)}%`;
}

function updateText(element, value, changedValues) {
  if (!element || element.textContent === value) return;
  element.textContent = value;
  changedValues.push(element);
}
