export function createPageLifecycle({
  onBackgroundChange,
  onForeground,
  onStart,
  onStop,
  onDispose,
}) {
  let started = false;
  let disposed = false;

  function start() {
    if (started || disposed) return;
    started = true;
    document.addEventListener("visibilitychange", syncBackgroundState);
    window.addEventListener("focus", syncBackgroundState);
    window.addEventListener("blur", syncBackgroundState);
    window.addEventListener("pagehide", handlePageHide);
    window.addEventListener("pageshow", handlePageShow);
    syncBackgroundState();
    onStart();
  }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (started) {
      document.removeEventListener("visibilitychange", syncBackgroundState);
      window.removeEventListener("focus", syncBackgroundState);
      window.removeEventListener("blur", syncBackgroundState);
      window.removeEventListener("pagehide", handlePageHide);
      window.removeEventListener("pageshow", handlePageShow);
    }
    onDispose();
  }

  function syncBackgroundState() {
    if (disposed) return;
    const backgrounded = document.hidden || !document.hasFocus();
    onBackgroundChange(backgrounded);
    if (!backgrounded) onForeground();
  }

  function handlePageHide(event) {
    onBackgroundChange(true);
    if (event.persisted) {
      onStop();
      return;
    }
    dispose();
  }

  function handlePageShow(event) {
    if (!event.persisted || disposed) return;
    syncBackgroundState();
    onStart();
  }

  return {
    dispose,
    isDisposed: () => disposed,
    start,
  };
}
