import { proxyJson } from "../../../../../lib/backend";
import { readJsonObject, requestInputErrorResponse } from "../../../../../lib/requestBody";
import { guardMutation } from "../../../../../lib/requestSecurity";

export async function POST(request: Request, { params }: { params: Promise<{ draftId: string }> }) {
  const denied = guardMutation(request, { bucket: "admin-takedown-send", limit: 6 });
  if (denied) return denied;
  try {
    const body = await readJsonObject(request);
    const { draftId } = await params;
    return proxyJson(`/v1/admin/takedowns/${encodeURIComponent(draftId)}/send`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-Type": "application/json" },
      timeoutMs: 75_000,
      retry: false,
      warmup: true,
    });
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json(
      { detail: "The takedown send request could not be read.", error_code: "TAKEDOWN_SEND_INVALID" },
      { status: 400 },
    );
  }
}
