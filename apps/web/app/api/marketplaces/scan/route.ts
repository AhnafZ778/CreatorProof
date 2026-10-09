import { proxyJson } from "../../../lib/backend";
import { readJsonObject, requestInputErrorResponse } from "../../../lib/requestBody";
import { guardMutation } from "../../../lib/requestSecurity";

export const maxDuration = 60;

export async function POST(request: Request) {
  const denied = guardMutation(request, { bucket: "marketplace-scan", limit: 12 });
  if (denied) return denied;
  try {
    const body = await readJsonObject(request);
    return proxyJson("/v1/marketplaces/scan", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      timeoutMs: 100_000,
      retry: false,
      warmup: true,
    });
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json(
      { detail: "The marketplace scan request could not be read.", error_code: "MARKETPLACE_REQUEST_INVALID" },
      { status: 400 },
    );
  }
}
