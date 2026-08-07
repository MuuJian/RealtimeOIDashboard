import { assertSignalScanPayload } from "./SignalScanPayloadSchema.js";

export async function loadSignalScanSnapshot({ signal } = {}) {
  const controller = new AbortController();
  let abortReason = null;
  const abort = reason => {
    abortReason ??= reason;
    controller.abort();
  };
  const timeout = window.setTimeout(() => abort("timeout"), 8000);
  const abortRequest = () => abort("cancelled");
  if (signal?.aborted) {
    abortRequest();
  } else {
    signal?.addEventListener("abort", abortRequest, { once: true });
  }

  try {
    throwIfAborted(controller.signal, abortReason);
    const response = await fetch("/api/signal-scan", {
      cache: "no-store",
      signal: controller.signal,
    });
    throwIfAborted(controller.signal, abortReason);
    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      if (error?.name === "AbortError") throw error;
      payload = null;
    }
    throwIfAborted(controller.signal, abortReason);
    if (!response.ok) {
      const detail = typeof payload?.error === "string"
        && payload.error.trim().length > 0
        ? `：${payload.error}`
        : "";
      throw new Error(`訊號掃描请求失败 (${response.status})${detail}`);
    }

    return assertSignalScanPayload(payload);
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

function throwIfAborted(signal, reason) {
  if (!signal.aborted) return;
  throw createAbortError(reason);
}

function createAbortError(reason) {
  const normalizedReason = reason === "cancelled" ? "cancelled" : "timeout";
  const error = new Error(
    normalizedReason === "cancelled"
      ? "訊號掃描请求已取消"
      : "訊號掃描请求超时",
  );
  error.name = "AbortError";
  error.code = "ABORTED";
  error.reason = normalizedReason;
  return error;
}
