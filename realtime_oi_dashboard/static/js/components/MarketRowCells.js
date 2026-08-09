import {
  binanceFuturesUrl,
  formatCurrency,
  formatFundingRate,
  formatPercent,
  formatPrice,
  formatRatioPercent,
  heatStyle,
  signClass,
  tradingViewUrl,
} from "../utils/format.js";
import {
  cvdStatusLabel,
  formatCvd,
  formatCvdAmount,
  formatCvdRatio,
} from "../utils/cvd.js";
import {
  createOiUpdateSignalCell,
  updateOiUpdateSignalCell,
} from "./OiUpdateSignal.js";

export function createMarketRowCells({
  includeMarketCap = false,
  includeOiToMarketCapRatio = false,
  includeCvd = false,
  oiChangesBeforeValue = false,
} = {}) {
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
  const oiToMarketCapRatioCell = includeOiToMarketCapRatio
    ? document.createElement("td")
    : null;
  const volumeCell = document.createElement("td");
  const oi24hChangeCell = document.createElement("td");
  const oi7dChangeCell = document.createElement("td");
  const oiUpdatedAtCell = createOiUpdateSignalCell();
  const cvdCell = includeCvd ? document.createElement("td") : null;
  const cvdAmount = includeCvd ? document.createElement("span") : null;
  const cvdRatio = includeCvd ? document.createElement("span") : null;
  const cvdStatusCell = includeCvd ? document.createElement("td") : null;
  const oiChangeCells = [oi24hChangeCell, oi7dChangeCell];

  if (cvdCell) {
    cvdAmount.className = "cvd-amount";
    cvdRatio.className = "cvd-ratio";
    cvdCell.append(cvdAmount, cvdRatio);
  }

  return {
    orderedCells: [
      symbolCell,
      priceCell,
      fundingRateCell,
      priceChangeCell,
      price7dChangeCell,
      ...(oiChangesBeforeValue ? oiChangeCells : []),
      oiValueCell,
      ...(marketCapCell ? [marketCapCell] : []),
      ...(oiToMarketCapRatioCell ? [oiToMarketCapRatioCell] : []),
      volumeCell,
      ...(!oiChangesBeforeValue ? oiChangeCells : []),
      ...(cvdCell ? [cvdCell, cvdStatusCell] : []),
      oiUpdatedAtCell,
    ],
    symbolLink,
    priceLink,
    fundingRateCell,
    priceChangeCell,
    price7dChangeCell,
    oiValueCell,
    marketCapCell,
    oiToMarketCapRatioCell,
    volumeCell,
    oi24hChangeCell,
    oi7dChangeCell,
    cvdCell,
    cvdAmount,
    cvdRatio,
    cvdStatusCell,
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
  if (cells.oiToMarketCapRatioCell) {
    cells.oiToMarketCapRatioCell.textContent = formatRatioPercent(
      row.oiToMarketCapRatio,
    );
  }
  cells.volumeCell.textContent = formatCurrency(row.volume24h);
  updateOiUpdateSignalCell(cells.oiUpdatedAtCell, row.oiUpdatedAt);
  if (cells.cvdCell) {
    cells.cvdAmount.textContent = formatCvdAmount(row.cvd15m);
    cells.cvdRatio.textContent = formatCvdRatio(row.cvd15mRatio);
    cells.cvdCell.className = `cvd-value ${signClass(row.cvd15m)}`;
    cells.cvdCell.title = formatCvd(row.cvd15m, row.cvd15mRatio);
    const cvdState = row.cvdHealth || row.cvdStatus || "unavailable";
    cells.cvdStatusCell.textContent = cvdStatusLabel(
      row.cvdStatus,
      row.cvdHealth,
    );
    cells.cvdStatusCell.className = `cvd-status cvd-status-${cvdState}`;
    cells.cvdStatusCell.title = row.cvdReason
      || "CVD 反映主動買賣流，不保證價格方向。";
  }

  cells.fundingRateCell.removeAttribute("title");
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
    ? `7 天前參考價：${formatPrice(row.price7dBaseline)}`
    : "等待 7 天歷史價格";
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
