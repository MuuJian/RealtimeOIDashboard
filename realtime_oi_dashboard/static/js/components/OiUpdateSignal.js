import {
  formatOiUpdateAge,
  formatOiUpdateTitle,
  oiUpdateSignalState,
} from "../utils/format.js";

const STATUS_LABELS = Object.freeze({
  fresh: "数据新鲜",
  warning: "数据开始变旧",
  danger: "数据接近失效",
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
    ? `OI 更新状态：${status}`
    : `OI 更新状态：${status}，${age}`;

  cell.className = `oi-update-cell oi-update-${state}`;
  cell.title = exactTime ? `${details} · ${exactTime}` : details;
  cell.setAttribute("aria-label", details);
}
