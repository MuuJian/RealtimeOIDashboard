import { formatCurrency, formatUtc8DateTime } from "../utils/format.js";
import { buildOiDominance } from "../utils/oiDominance.js";

const tooltipStates = new WeakMap();

export function renderOiDominance(elements, rows, history) {
  const dominance = buildOiDominance(rows, history);
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
    item.title = dominance.total > 0
      ? `${group.label}：${formatShare(group.percent)} · ${formatCurrency(group.value)}`
      : "暫無資料";
  }

  updateTooltipState(elements, dominance.points);

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

function updateTooltipState(elements, points) {
  const chart = elements.oiDominanceBar;
  const tooltip = elements.oiDominanceTooltip;
  if (!chart || !tooltip) return;

  let state = tooltipStates.get(chart);
  if (!state) {
    state = { points: [] };
    tooltipStates.set(chart, state);
    chart.addEventListener("pointermove", event => {
      if (event.pointerType === "touch" || !state.points.length) return;
      showTooltip(chart, tooltip, state.points, event.clientX);
    });
    chart.addEventListener("pointerleave", () => {
      tooltip.hidden = true;
    });
  }
  state.points = points;
}

function showTooltip(
  chart,
  tooltip,
  points,
  clientX,
) {
  const rect = chart.getBoundingClientRect();
  const ratio = Math.max(0, Math.min((clientX - rect.left) / rect.width, 1));
  const index = Math.round(ratio * (points.length - 1));
  const point = points[index];
  const pixelX = ratio * rect.width;
  const tooltipWidth = 190;

  tooltip.hidden = false;
  tooltip.style.left = `${Math.max(
    0,
    Math.min(pixelX + 10, rect.width - tooltipWidth),
  )}px`;
  tooltip.querySelector("[data-oi-dominance-time]").textContent =
    formatUtc8DateTime(point.timestamp) || "-";

  for (const group of point.groups) {
    const row = tooltip.querySelector(
      `[data-oi-dominance-tooltip="${group.key}"]`,
    );
    if (!row) continue;
    row.querySelector("strong").textContent = formatShare(group.percent);
    row.querySelector("em").textContent = formatCurrency(group.value);
  }
}

function areaPath(points, key) {
  const width = 320;
  const height = 76;
  const xValues = points.map((_, index) => (
    points.length === 1 ? 0 : index / (points.length - 1) * width
  ));
  const stackOrder = ["other", "eth", "btc"];
  const groupIndex = stackOrder.indexOf(key);
  const lower = points.map(point => stackOrder
    .slice(0, groupIndex)
    .reduce((sum, stackKey) => sum + groupPercent(point, stackKey), 0));
  const upper = points.map((point, index) => (
    lower[index] + groupPercent(point, key)
  ));
  const y = percent => height - Math.max(0, Math.min(percent, 100)) / 100 * height;

  const upperLine = xValues
    .map((x, index) => (
      `${index ? "L" : "M"} ${x.toFixed(2)} ${y(upper[index]).toFixed(2)}`
    ))
    .join(" ");
  const lowerLine = xValues
    .map((_, reverseIndex) => {
      const index = xValues.length - 1 - reverseIndex;
      return `L ${xValues[index].toFixed(2)} ${y(lower[index]).toFixed(2)}`;
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
