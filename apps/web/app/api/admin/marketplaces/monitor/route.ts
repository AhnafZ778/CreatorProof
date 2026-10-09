import { proxyJson } from "../../../../lib/backend";
import { readJsonObject, requestInputErrorResponse } from "../../../../lib/requestBody";
import { guardMutation } from "../../../../lib/requestSecurity";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const params = new URLSearchParams();
  for (const key of ["limit", "offset"]) {
    const value = url.searchParams.get(key);
    if (value) params.set(key, value);
  }
  return proxyJson(`/v1/admin/marketplaces/monitor?${params}`, { timeoutMs: 75_000 });
}

export async function POST(request: Request) {
  const denied = guardMutation(request, { bucket: "admin-marketplace-monitor", limit: 6 });
  if (denied) return denied;
  try {
    const body = await readJsonObject(request);
    return proxyJson("/v1/admin/marketplaces/monitor", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      timeoutMs: 180_000,
      retry: false,
      warmup: true,
    });
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json(
      { detail: "The admin monitor request could not be read.", error_code: "ADMIN_MONITOR_INVALID" },
      { status: 400 },
    );
  }
}
