export function createPageLifecycle({
  onActiveChange,
  onDispose,
}) {
  let started = false;
  let disposed = false;

  function start() {
    if (started || disposed) return;
    started = true;
    document.addEventListener("visibilitychange", syncActiveState);
    window.addEventListener("focus", syncActiveState);
    window.addEventListener("blur", syncActiveState);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", handlePageShow);
    syncActiveState();
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (started) {
      document.removeEventListener("visibilitychange", syncActiveState);
      window.removeEventListener("focus", syncActiveState);
      window.removeEventListener("blur", syncActiveState);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", handlePageShow);
    }
    onDispose();
  }

  function syncActiveState() {
    if (disposed) return;
    const pageActive = document.hidden !== true
      && document.visibilityState !== "hidden"
      && document.visibilityState !== "prerender"
      && document.hasFocus();
    onActiveChange(pageActive);
  }

  function handlePageHide(event) {
    onActiveChange(false);
    if (event.persisted) return;
    dispose();
  }

  function handlePageShow() {
    syncActiveState();
  }

  return {
    dispose,
    isDisposed: () => disposed,
    start,
  };
}
