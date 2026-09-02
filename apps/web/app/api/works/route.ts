import { proxyJson } from "../../lib/backend";
import { readImageForm, readJsonObject, requestInputErrorResponse } from "../../lib/requestBody";
import { guardMutation } from "../../lib/requestSecurity";

// Origin screening on enrollment can run OCR, C2PA, and the synthetic ensemble
// before the API writes a row. Cap at the Hobby Fluid limit (60s) so the
// deployment is accepted; Pro can raise this with the rest of the function budget.
export const maxDuration = 60;

export async function POST(request: Request) {
  const denied = guardMutation(request, { bucket: "work-create", limit: 12 });
  if (denied) return denied;
  try {
    const isJson = request.headers.get("content-type")?.toLowerCase().startsWith("application/json");
    const input = isJson ? await readJsonObject(request) : await readImageForm(request);
    if (isJson && typeof (input as Record<string, unknown>).upload_token !== "string") {
      return Response.json(
        { detail: "upload_token is required.", error_code: "UPLOAD_TOKEN_REQUIRED" },
        { status: 400 },
      );
    }
    return proxyJson(isJson ? "/v1/works/from-upload" : "/v1/works", {
      method: "POST",
      body: isJson ? JSON.stringify(input) : (input as FormData),
      headers: isJson ? { "Content-Type": "application/json" } : {},
      timeoutMs: 170_000,
      // A direct-upload token maps to one deterministic work identifier.
      // Multipart registration has no idempotency key and is never replayed.
      retry: isJson,
      warmup: true,
    });
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json(
      { detail: "The registration request could not be read.", error_code: "WORK_REQUEST_INVALID" },
      { status: 400 },
    );
  }
}

/**
 * List what a catalog actually holds. A scan can only find what was registered,
 * so the scan desk reads this before running to tell the operator whether the
 * catalog they typed has anything in it to match against.
 */
export async function GET(request: Request) {
  const catalogId = new URL(request.url).searchParams.get("catalog_id");
  const query = catalogId ? `?catalog_id=${encodeURIComponent(catalogId)}` : "";
  return proxyJson(`/v1/works${query}`);
}
