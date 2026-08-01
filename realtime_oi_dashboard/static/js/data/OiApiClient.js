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
    const response = await fetch("/api/oi", {
      cache: "no-store",
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`OI 请求失败 (${response.status})`);

    return assertOiPayload(await response.json());
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new Error(
        abortReason === "cancelled" ? "OI 请求已取消" : "OI 请求超时",
      );
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    signal?.removeEventListener("abort", abortRequest);
  }
}
