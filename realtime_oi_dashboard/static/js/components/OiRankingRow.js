import {
  binanceFuturesUrl,
  formatCurrency,
  formatFundingTitle,
  formatFundingRate,
  formatPercent,
  formatPrice,
  heatStyle,
  signClass,
  tradingViewUrl,
} from "../utils/format.js";

export function createRankingRow(row, context) {
  const tr = document.createElement("tr");
  tr.dataset.symbol = row.symbol;

  const favoriteCell = document.createElement("td");
  favoriteCell.className = "favorite-cell";
  const favoriteButton = document.createElement("button");
  favoriteButton.className = "favorite-btn";
  favoriteButton.type = "button";
  favoriteButton.textContent = "★";
  favoriteCell.append(favoriteButton);

  const symbolCell = document.createElement("td");
  symbolCell.className = "symbol";
  const symbolLink = document.createElement("a");
  symbolLink.className = "symbol-link";
  symbolLink.target = "_blank";
  symbolLink.rel = "noopener noreferrer";
  symbolCell.append(symbolLink);

  const priceCell = document.createElement("td");
  const priceLink = document.createElement("a");
  priceLink.className = "symbol-link";
  priceLink.target = "_blank";
  priceLink.rel = "noopener noreferrer";
  priceCell.append(priceLink);

  const priceChangeCell = document.createElement("td");
  const price7dChangeCell = document.createElement("td");
  const fundingRateCell = document.createElement("td");
  const oiValueCell = document.createElement("td");
  const volumeCell = document.createElement("td");
  const oi24hChangeCell = document.createElement("td");
  const oi7dChangeCell = document.createElement("td");

  tr.append(
    favoriteCell,
    symbolCell,
    priceCell,
    fundingRateCell,
    priceChangeCell,
    price7dChangeCell,
    oiValueCell,
    volumeCell,
    oi24hChangeCell,
    oi7dChangeCell,
  );

  tr._cells = {
    favoriteButton,
    symbolLink,
    fundingRateCell,
    priceLink,
    priceChangeCell,
    price7dChangeCell,
    oiValueCell,
    volumeCell,
    oi24hChangeCell,
    oi7dChangeCell,
  };

  updateRankingRow(tr, row, context);
  return tr;
}

export function updateRankingRow(tr, row, context) {
  const cells = tr._cells;
  const isFavorite = context.favorites.has(row.symbol);
  tr.dataset.symbol = row.symbol;

  cells.favoriteButton.dataset.favorite = row.symbol;
  cells.favoriteButton.classList.toggle("active", isFavorite);
  cells.favoriteButton.title = isFavorite ? "取消收藏" : "加入收藏";
  cells.favoriteButton.setAttribute("aria-pressed", String(isFavorite));
  cells.favoriteButton.setAttribute(
    "aria-label",
    `${isFavorite ? "取消收藏" : "加入收藏"} ${row.symbol}`,
  );

  cells.symbolLink.href = binanceFuturesUrl(row.symbol);
  cells.symbolLink.textContent = row.symbol;
  cells.priceLink.href = tradingViewUrl(row.symbol);
  cells.priceLink.textContent = formatPrice(row.price);
  cells.oiValueCell.textContent = formatCurrency(row.currentOiValue);
  cells.volumeCell.textContent = formatCurrency(row.volume24h);

  updateHeatCell(
    cells.priceChangeCell,
    row.priceChangePercent,
    context.heatMax.priceChangePercent,
  );
  cells.price7dChangeCell.title = Number.isFinite(row.price7dBaseline)
    ? `7 天前参考价：${formatPrice(row.price7dBaseline)}`
    : "等待 7 天历史价格";
  updateHeatCell(
    cells.price7dChangeCell,
    row.price7dChangePercent,
    context.heatMax.price7dChangePercent,
  );
  cells.fundingRateCell.title = formatFundingTitle(row.nextFundingTime);
  updateHeatCell(
    cells.fundingRateCell,
    row.fundingRatePercent,
    context.heatMax.fundingRatePercent,
    formatFundingRate,
  );
  updateHeatCell(
    cells.oi24hChangeCell,
    row.oi24hChangePercent,
    context.heatMax.oi24hChangePercent,
  );
  updateHeatCell(
    cells.oi7dChangeCell,
    row.oi7dChangePercent,
    context.heatMax.oi7dChangePercent,
  );
}

function updateHeatCell(cell, value, max, formatter = formatPercent) {
  cell.className = `heat ${signClass(value)}`;
  cell.style.cssText = heatStyle(value, max);
  cell.textContent = formatter(value);
}
