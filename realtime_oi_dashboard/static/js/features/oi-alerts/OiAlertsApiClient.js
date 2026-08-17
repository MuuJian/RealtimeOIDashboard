const REQUEST_TIMEOUT_MS = 8000;

export function loadOiAlerts({ signal } = {}) {
  return requestOiAlerts("/api/oi-alerts", { method: "GET", signal });
}

export function saveOiAlertsConfig({ enabled, thresholds }, { signal } = {}) {
  const body = {
    enabled,
    thresholds,
  };
  return requestOiAlerts("/api/oi-alerts/config", {
    method: "PUT",
    body,
    signal,
  });
}

export function sendOiAlertsTestMessage({ signal } = {}) {
  return requestOiAlerts("/api/oi-alerts/test-message", {
    method: "POST",
    body: {},
    signal,
  });
}

async function requestOiAlerts(url, { method, body, signal }) {
  const controller = new AbortController();
  let abortReason = null;
  const abort = reason => {
    abortReason ??= reason;
    controller.abort();
  };
  const timeout = window.setTimeout(() => abort("timeout"), REQUEST_TIMEOUT_MS);
  const abortRequest = () => abort("cancelled");
  if (signal?.aborted) abortRequest();
  else signal?.addEventListener("abort", abortRequest, { once: true });

  try {
    throwIfAborted(controller.signal, abortReason);
    const response = await fetch(url, {
      method,
      cache: "no-cache",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    throwIfAborted(controller.signal, abortReason);
    const payload = await parseJson(response);
    throwIfAborted(controller.signal, abortReason);
    if (!response.ok) {
      const message = typeof payload?.error === "string" && payload.error.trim()
        ? payload.error
        : `OI alerts request failed (${response.status})`;
      throw new Error(message);
    }
    return payload;
  } catch (error) {
    if (controller.signal.aborted || error?.name === "AbortError") {
      throw createAbortError(abortReason);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener("abort", abortRequest);
  }
}

async function parseJson(response) {
  try {
    return await response.json();
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return null;
  }
}

function throwIfAborted(signal, reason) {
  if (signal.aborted) throw createAbortError(reason);
}

function createAbortError(reason) {
  const normalizedReason = reason === "cancelled" ? "cancelled" : "timeout";
  const error = new Error(
    normalizedReason === "cancelled"
      ? "OI alerts request cancelled"
      : "OI alerts request timed out",
  );
  error.name = "AbortError";
  error.code = "ABORTED";
  error.reason = normalizedReason;
  return error;
}
