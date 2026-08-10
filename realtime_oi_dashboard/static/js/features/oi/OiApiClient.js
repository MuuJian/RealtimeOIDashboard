import { assertOiPayload } from "./OiPayloadSchema.js";

export async function loadOiSnapshot({ signal } = {}) {
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
    const response = await fetch("/api/oi", {
      cache: "no-store",
      signal: controller.signal,
    });
    throwIfAborted(controller.signal, abortReason);
    if (!response.ok) throw new Error(`OI 請求失敗 (${response.status})`);

    const payload = await response.json();
    throwIfAborted(controller.signal, abortReason);
    return assertOiPayload(payload);
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
    normalizedReason === "cancelled" ? "OI 請求已取消" : "OI 請求超時",
  );
  error.name = "AbortError";
  error.code = "ABORTED";
  error.reason = normalizedReason;
  return error;
}
