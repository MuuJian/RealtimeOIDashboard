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
    const response = await fetch("/api/signal-scan", {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`訊號掃描请求失败 (${response.status})`);

    return assertSignalScanPayload(await response.json());
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(
        abortReason === "cancelled" ? "訊號掃描请求已取消" : "訊號掃描请求超时",
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener("abort", abortRequest);
  }
}
