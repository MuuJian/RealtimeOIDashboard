export function getDashboardElements(root = document) {
  return {
    statusTitle: root.getElementById("statusTitle"),
    statusText: root.getElementById("statusText"),
    wsState: root.getElementById("wsState"),
    topIncrease: root.getElementById("topIncrease"),
    topIncreaseNote: root.getElementById("topIncreaseNote"),
    topDecrease: root.getElementById("topDecrease"),
    topDecreaseNote: root.getElementById("topDecreaseNote"),
    searchInput: root.getElementById("searchInput"),
    sortSelect: root.getElementById("sortSelect"),
    favoritesOnlyBtn: root.getElementById("favoritesOnlyBtn"),
    oiValueFilter: root.getElementById("oiValueFilter"),
    volumeFilter: root.getElementById("volumeFilter"),
    limitSelect: root.getElementById("limitSelect"),
    signalOi7dFilter: root.getElementById("signalOi7dFilter"),
    signalOiValueFilter: root.getElementById("signalOiValueFilter"),
    rankBody: root.getElementById("rankBody"),
    highOi7dBody: root.getElementById("highOi7dBody"),
    sortableHeaders: root.querySelectorAll("th[data-sort]"),
  };
}
