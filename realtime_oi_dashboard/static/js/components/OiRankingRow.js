import {
  createMarketRowCells,
  updateMarketRowCells,
} from "./MarketRowCells.js";

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

  const marketCells = createMarketRowCells();
  tr.append(favoriteCell, ...marketCells.orderedCells);

  tr._cells = {
    favoriteButton,
    market: marketCells,
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

  updateMarketRowCells(cells.market, row, context.heatMax);
}
