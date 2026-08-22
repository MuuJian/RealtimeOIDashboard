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
      segment.setAttribute("d", areaPath(dominance.points, group.key));
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
    item.title = dominance.total > 0
      ? `${group.label}：${formatCurrency(group.value)}`
      : "暫無資料";
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

function areaPath(points, key) {
  const width = 320;
  const height = 76;
  const xValues = [0, width / 2, width];
  const stackOrder = ["other", "sol", "eth", "btc"];
  const groupIndex = stackOrder.indexOf(key);
  const lower = points.map(point => stackOrder
    .slice(0, groupIndex)
    .reduce((sum, stackKey) => sum + groupPercent(point, stackKey), 0));
  const upper = points.map((point, index) => (
    lower[index] + groupPercent(point, key)
  ));
  const y = percent => height - Math.max(0, Math.min(percent, 100)) / 100 * height;

  const upperLine = xValues
    .map((x, index) => `${index ? "L" : "M"} ${x} ${y(upper[index])}`)
    .join(" ");
  const lowerLine = xValues
    .map((_, reverseIndex) => {
      const index = xValues.length - 1 - reverseIndex;
      return `L ${xValues[index]} ${y(lower[index])}`;
    })
    .join(" ");
  return `${upperLine} ${lowerLine} Z`;
}

function groupPercent(point, key) {
  return point.groups.find(group => group.key === key)?.percent || 0;
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
