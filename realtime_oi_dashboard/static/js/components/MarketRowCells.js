import {
  binanceFuturesUrl,
  formatCurrency,
  formatFundingRate,
  formatFundingTitle,
  formatPercent,
  formatPrice,
  heatStyle,
  signClass,
  tradingViewUrl,
} from "../utils/format.js";
import {
  createOiUpdateSignalCell,
  updateOiUpdateSignalCell,
} from "./OiUpdateSignal.js";

export function createMarketRowCells({ includeMarketCap = false } = {}) {
  const symbolCell = document.createElement("td");
  symbolCell.className = "symbol";
  const symbolLink = createLink();
  symbolCell.append(symbolLink);

  const priceCell = document.createElement("td");
  const priceLink = createLink();
  priceCell.append(priceLink);

  const fundingRateCell = document.createElement("td");
  const priceChangeCell = document.createElement("td");
  const price7dChangeCell = document.createElement("td");
  const oiValueCell = document.createElement("td");
  const marketCapCell = includeMarketCap ? document.createElement("td") : null;
  const volumeCell = document.createElement("td");
  const oi24hChangeCell = document.createElement("td");
  const oi7dChangeCell = document.createElement("td");
  const oiUpdatedAtCell = createOiUpdateSignalCell();

  return {
    orderedCells: [
      symbolCell,
      priceCell,
      fundingRateCell,
      priceChangeCell,
      price7dChangeCell,
      oiValueCell,
      ...(marketCapCell ? [marketCapCell] : []),
      volumeCell,
      oi24hChangeCell,
      oi7dChangeCell,
      oiUpdatedAtCell,
    ],
    symbolLink,
    priceLink,
    fundingRateCell,
    priceChangeCell,
    price7dChangeCell,
    oiValueCell,
    marketCapCell,
    volumeCell,
    oi24hChangeCell,
    oi7dChangeCell,
    oiUpdatedAtCell,
  };
}

export function updateMarketRowCells(cells, row, heatMax = null) {
  cells.symbolLink.href = binanceFuturesUrl(row.symbol);
  cells.symbolLink.textContent = row.symbol;
  cells.priceLink.href = tradingViewUrl(row.symbol);
  cells.priceLink.textContent = formatPrice(row.price);
  cells.oiValueCell.textContent = formatCurrency(row.currentOiValue);
  if (cells.marketCapCell) {
    cells.marketCapCell.textContent = formatCurrency(row.marketCap);
  }
  cells.volumeCell.textContent = formatCurrency(row.volume24h);
  updateOiUpdateSignalCell(cells.oiUpdatedAtCell, row.oiUpdatedAt);

  cells.fundingRateCell.title = formatFundingTitle(row.nextFundingTime);
  updateSignedCell(
    cells.fundingRateCell,
    row.fundingRatePercent,
    formatFundingRate,
    heatMax?.fundingRatePercent,
  );
  updateSignedCell(
    cells.priceChangeCell,
    row.priceChangePercent,
    formatPercent,
    heatMax?.priceChangePercent,
  );

  cells.price7dChangeCell.title = Number.isFinite(row.price7dBaseline)
    ? `7 天前参考价：${formatPrice(row.price7dBaseline)}`
    : "等待 7 天历史价格";
  updateSignedCell(
    cells.price7dChangeCell,
    row.price7dChangePercent,
    formatPercent,
    heatMax?.price7dChangePercent,
  );
  updateSignedCell(
    cells.oi24hChangeCell,
    row.oi24hChangePercent,
    formatPercent,
    heatMax?.oi24hChangePercent,
  );
  updateSignedCell(
    cells.oi7dChangeCell,
    row.oi7dChangePercent,
    formatPercent,
    heatMax?.oi7dChangePercent,
  );
}

function createLink() {
  const link = document.createElement("a");
  link.className = "symbol-link";
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function updateSignedCell(cell, value, formatter, maximum) {
  cell.className = `heat ${signClass(value)}`;
  cell.style.cssText = Number.isFinite(maximum)
    ? heatStyle(value, maximum)
    : "";
  cell.textContent = formatter(value);
}
