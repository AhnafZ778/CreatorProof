import { proxyJson } from "../../../../lib/backend";
import { readBoundedText, requestInputErrorResponse } from "../../../../lib/requestBody";
import { guardMutation } from "../../../../lib/requestSecurity";

export async function POST(request: Request, context: { params: Promise<{ scanId: string }> }) {
  const denied = guardMutation(request, { bucket: "scan-cancel", limit: 20 });
  if (denied) return denied;
  const { scanId } = await context.params;
  let body: string;
  try {
    body = await readBoundedText(request);
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json({}, { status: 400 });
  }
  return proxyJson(`/v1/scans/${encodeURIComponent(scanId)}/cancel`, {
    method: "POST",
    body: body || JSON.stringify({ reason: "Cancelled from the console" }),
    headers: { "Content-Type": "application/json" },
    timeoutMs: 90_000,
    warmup: true,
  });
}
