const PAGE_OI = "oi";
const PAGE_SIGNAL_SCAN = "signalScan";
const PAGE_OI_ALERTS = "oiAlerts";
const MODE_PAUSED = "paused";

export function createLiveUpdateCoordinator({
  oiRefresh,
  signalScanRefresh,
  oiAlertsRefresh,
  priceFeed,
  selectedPage = PAGE_OI,
  pageActive = false,
}) {
  assertPage(selectedPage);

  let currentPage = selectedPage;
  let active = Boolean(pageActive);
  let appliedMode = null;
  let disposed = false;

  function setSelectedPage(nextPage) {
    if (disposed) return;
    assertPage(nextPage);
    if (currentPage === nextPage) return;
    currentPage = nextPage;
    reconcile();
  }

  function setPageActive(nextActive) {
    if (disposed) return;
    const normalizedActive = Boolean(nextActive);
    if (active === normalizedActive && appliedMode !== null) return;
    active = normalizedActive;
    reconcile();
  }

  function reconcile() {
    const nextMode = active ? currentPage : MODE_PAUSED;
    if (appliedMode === nextMode) return;

    if (nextMode === MODE_PAUSED) {
      oiRefresh.stop();
      signalScanRefresh.stop();
      oiAlertsRefresh.stop();
      priceFeed.close();
    } else if (nextMode === PAGE_OI) {
      signalScanRefresh.stop();
      oiAlertsRefresh.stop();
      priceFeed.connect();
      oiRefresh.start();
    } else if (nextMode === PAGE_SIGNAL_SCAN) {
      oiRefresh.stop();
      oiAlertsRefresh.stop();
      priceFeed.close();
      signalScanRefresh.start();
    } else {
      oiRefresh.stop();
      signalScanRefresh.stop();
      priceFeed.close();
      oiAlertsRefresh.start();
    }

    appliedMode = nextMode;
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    appliedMode = MODE_PAUSED;
    oiRefresh.dispose();
    signalScanRefresh.dispose();
    oiAlertsRefresh.dispose();
    priceFeed.close();
  }

  return {
    dispose,
    getState: () => ({
      pageActive: active,
      selectedPage: currentPage,
    }),
    isDisposed: () => disposed,
    setPageActive,
    setSelectedPage,
  };
}

function assertPage(page) {
  if (
    page !== PAGE_OI
    && page !== PAGE_SIGNAL_SCAN
    && page !== PAGE_OI_ALERTS
  ) {
    throw new TypeError(`Unknown live-update page: ${page}`);
  }
}
