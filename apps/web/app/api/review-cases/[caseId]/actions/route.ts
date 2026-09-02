import { proxyJson } from "../../../../lib/backend";
import { readBoundedText, requestInputErrorResponse } from "../../../../lib/requestBody";
import { guardMutation } from "../../../../lib/requestSecurity";

export async function POST(request: Request, context: { params: Promise<{ caseId: string }> }) {
  const denied = guardMutation(request, { bucket: "review-action", limit: 20 });
  if (denied) return denied;
  const { caseId } = await context.params;
  let body: string;
  try {
    body = await readBoundedText(request);
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json({}, { status: 400 });
  }
  return proxyJson(`/v1/review-cases/${encodeURIComponent(caseId)}/actions`, {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
    timeoutMs: 90_000,
    warmup: true,
  });
}
