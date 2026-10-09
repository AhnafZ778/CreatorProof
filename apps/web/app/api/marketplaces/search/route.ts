import { proxyJson } from "../../../lib/backend";
import { readJsonObject, requestInputErrorResponse } from "../../../lib/requestBody";
import { guardMutation } from "../../../lib/requestSecurity";

export async function POST(request: Request) {
  const denied = guardMutation(request, { bucket: "marketplace-search", limit: 20 });
  if (denied) return denied;
  try {
    const body = await readJsonObject(request);
    return proxyJson("/v1/marketplaces/search", {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      timeoutMs: 75_000,
      retry: false,
      warmup: true,
    });
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json(
      { detail: "The marketplace search request could not be read.", error_code: "MARKETPLACE_REQUEST_INVALID" },
      { status: 400 },
    );
  }
}
