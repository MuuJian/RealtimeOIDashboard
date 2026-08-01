import {
  formatCurrency,
  formatFundingRate,
  formatOiUpdateAge,
  formatOiUpdateTitle,
  formatPercent,
  formatPrice,
  formatRatioPercent,
  signClass,
} from "../utils/format.js";

const TOOLTIP_OFFSET = 14;
const VIEWPORT_MARGIN = 10;

export function createMarketTooltip({ containers, getRowBySymbol }) {
  const tooltip = createTooltip();
  const listeners = [];
  let activeSymbol = null;

  document.body.append(tooltip);

  for (const container of containers) {
    listen(container, "pointerover", event => {
      if (event.pointerType === "touch") return;
      const tr = findRow(container, event.target);
      if (!tr) return;
      show(tr.dataset.symbol, event.clientX, event.clientY);
    });
    listen(container, "pointermove", event => {
      if (event.pointerType === "touch") return;
      if (!activeSymbol) return;
      positionTooltip(tooltip, event.clientX, event.clientY);
    });
    listen(container, "pointerout", event => {
      if (event.pointerType === "touch") return;
      const tr = findRow(container, event.target);
      if (!tr) return;
      if (
        event.relatedTarget instanceof Node
        && tr.contains(event.relatedTarget)
      ) return;
      hide();
    });
    listen(container, "pointerleave", event => {
      if (event.pointerType !== "touch") hide();
    });
    listen(container, "pointerup", event => {
      if (event.pointerType !== "touch" || isInteractiveTarget(event.target)) return;
      const tr = findRow(container, event.target);
      if (!tr) return;
      if (activeSymbol === tr.dataset.symbol) {
        hide();
        return;
      }
      show(tr.dataset.symbol, event.clientX, event.clientY);
    });
    listen(container, "focusin", event => {
      const tr = findRow(container, event.target);
      if (!tr) return;
      const rect = tr.getBoundingClientRect();
      show(tr.dataset.symbol, rect.left + rect.width / 2, rect.bottom);
    });
    listen(container, "focusout", event => {
      const tr = findRow(container, event.target);
      if (!tr) return;
      if (
        event.relatedTarget instanceof Node
        && tr.contains(event.relatedTarget)
      ) return;
      hide();
    });
  }

  const scrollContainers = new Set(
    containers.map(container => container.closest(".table-wrap")).filter(Boolean),
  );
  for (const container of scrollContainers) {
    listen(container, "scroll", hide, { passive: true });
  }
  listen(window, "resize", hide);
  listen(window, "scroll", hide, { passive: true });
  listen(document, "pointerdown", event => {
    if (event.pointerType !== "touch") return;
    const tappedRow = containers.some(
      container => findRow(container, event.target),
    );
    if (!tappedRow) hide();
  });

  function show(symbol, clientX, clientY) {
    const row = getRowBySymbol(symbol);
    if (!row) {
      hide();
      return;
    }

    activeSymbol = symbol;
    renderTooltip(tooltip, row);
    tooltip.hidden = false;
    positionTooltip(tooltip, clientX, clientY);
  }

  function hide() {
    activeSymbol = null;
    tooltip.hidden = true;
  }

  function listen(target, type, listener, options) {
    target.addEventListener(type, listener, options);
    listeners.push(() => target.removeEventListener(type, listener, options));
  }

  function dispose() {
    for (const removeListener of listeners) removeListener();
    tooltip.remove();
  }

  return { dispose };
}

function createTooltip() {
  const tooltip = document.createElement("aside");
  tooltip.className = "market-tooltip";
  tooltip.hidden = true;
  tooltip.setAttribute("role", "tooltip");

  const title = document.createElement("strong");
  title.className = "market-tooltip-title";

  const grid = document.createElement("dl");
  grid.className = "market-tooltip-grid";
  const fields = [
    "价格",
    "资金费率",
    "价格 24h",
    "价格 7d",
    "持仓价值",
    "市值",
    "持仓/市值",
    "成交额 24h",
    "持仓 24h",
    "持仓 7d",
    "OI 更新",
  ].map(label => {
    const item = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    item.append(term, detail);
    grid.append(item);
    return detail;
  });

  tooltip.append(title, grid);
  tooltip._title = title;
  tooltip._grid = grid;
  tooltip._fields = fields;
  return tooltip;
}

function renderTooltip(tooltip, row) {
  tooltip._title.textContent = row.symbol;
  const values = [
    [formatPrice(row.price)],
    [formatFundingRate(row.fundingRatePercent), row.fundingRatePercent],
    [formatPercent(row.priceChangePercent), row.priceChangePercent],
    [formatPercent(row.price7dChangePercent), row.price7dChangePercent],
    [formatCurrency(row.currentOiValue)],
    [formatCurrency(row.marketCap)],
    [formatRatioPercent(row.oiToMarketCapRatio)],
    [formatCurrency(row.volume24h)],
    [formatPercent(row.oi24hChangePercent), row.oi24hChangePercent],
    [formatPercent(row.oi7dChangePercent), row.oi7dChangePercent],
    [formatOiUpdateAge(row.oiUpdatedAt)],
  ];

  values.forEach(([value, signedValue], index) => {
    const detail = tooltip._fields[index];
    detail.textContent = value;
    detail.className = signedValue == null ? "" : signClass(signedValue);
  });

  const updatedTitle = formatOiUpdateTitle(row.oiUpdatedAt);
  tooltip._grid.title = updatedTitle;
}

function positionTooltip(tooltip, clientX, clientY) {
  const width = tooltip.offsetWidth;
  const height = tooltip.offsetHeight;
  let left = clientX + TOOLTIP_OFFSET;
  let top = clientY + TOOLTIP_OFFSET;

  if (left + width > window.innerWidth - VIEWPORT_MARGIN) {
    left = clientX - width - TOOLTIP_OFFSET;
  }
  if (top + height > window.innerHeight - VIEWPORT_MARGIN) {
    top = clientY - height - TOOLTIP_OFFSET;
  }

  left = Math.max(VIEWPORT_MARGIN, left);
  top = Math.max(VIEWPORT_MARGIN, top);
  tooltip.style.transform =
    `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;
}

function findRow(container, target) {
  if (!(target instanceof Element)) return null;
  const tr = target.closest("tr[data-symbol]");
  return tr && container.contains(tr) ? tr : null;
}

function isInteractiveTarget(target) {
  return target instanceof Element
    && Boolean(target.closest("a, button, input, select, textarea"));
}
