import {
  formatOiUpdateAge,
  formatOiUpdateTitle,
  oiUpdateSignalState,
} from "../utils/format.js";

const STATUS_LABELS = Object.freeze({
  fresh: "數據新鮮",
  warning: "數據開始變舊",
  danger: "數據接近失效",
});

export function createOiUpdateSignalCell() {
  const cell = document.createElement("td");
  const signal = document.createElement("span");
  signal.className = "oi-update-signal";
  signal.setAttribute("aria-hidden", "true");

  for (let index = 0; index < 5; index += 1) {
    const bar = document.createElement("span");
    bar.className = "oi-update-signal-bar";
    signal.append(bar);
  }

  cell.append(signal);
  return cell;
}

export function updateOiUpdateSignalCell(cell, value, now = Date.now()) {
  const state = oiUpdateSignalState(value, now);
  const age = formatOiUpdateAge(value, now);
  const status = age === "-" ? "尚未更新" : STATUS_LABELS[state];
  const exactTime = formatOiUpdateTitle(value);
  const details = age === "-"
    ? `OI 更新狀態：${status}`
    : `OI 更新狀態：${status}，${age}`;

  cell.className = `oi-update-cell oi-update-${state}`;
  cell.title = exactTime ? `${details} · ${exactTime}` : details;
  cell.setAttribute("aria-label", details);
}
