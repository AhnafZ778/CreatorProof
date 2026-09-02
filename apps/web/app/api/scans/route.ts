import { proxyJson } from "../../lib/backend";
import { readImageForm, readJsonObject, requestInputErrorResponse } from "../../lib/requestBody";
import { guardMutation } from "../../lib/requestSecurity";

export const maxDuration = 60;

export async function POST(request: Request) {
  const denied = guardMutation(request, { bucket: "scan-create", limit: 12 });
  if (denied) return denied;
  const idempotency = request.headers.get("Idempotency-Key") ?? crypto.randomUUID();
  try {
    const isJson = request.headers.get("content-type")?.toLowerCase().startsWith("application/json");
    const input = isJson ? await readJsonObject(request) : await readImageForm(request);
    if (isJson && typeof (input as Record<string, unknown>).upload_token !== "string") {
      return Response.json(
        { detail: "upload_token is required.", error_code: "UPLOAD_TOKEN_REQUIRED" },
        { status: 400 },
      );
    }
    return proxyJson(isJson ? "/v1/scans/from-upload" : "/v1/scans", {
      method: "POST",
      headers: {
        "Idempotency-Key": idempotency,
        ...(isJson ? { "Content-Type": "application/json" } : {}),
      },
      body: isJson ? JSON.stringify(input) : (input as FormData),
      timeoutMs: 100_000,
      // Multipart uses Idempotency-Key; direct completion is bound to the signed
      // upload nonce. Both paths can safely recover a response lost in transit.
      retry: true,
      warmup: true,
    });
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json(
      { detail: "The scan request could not be read.", error_code: "SCAN_REQUEST_INVALID" },
      { status: 400 },
    );
  }
}
