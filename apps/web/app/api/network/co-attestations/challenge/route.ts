import { proxyJson } from "../../../../lib/backend";
import { readBoundedText, requestInputErrorResponse } from "../../../../lib/requestBody";
import { guardMutation } from "../../../../lib/requestSecurity";

export async function POST(request: Request) {
  const denied = guardMutation(request, { bucket: "coattestation-challenge", limit: 20 });
  if (denied) return denied;
  let body: string;
  try {
    body = await readBoundedText(request);
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json({}, { status: 400 });
  }
  return proxyJson("/v1/network/co-attestations/challenge", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
    timeoutMs: 90_000,
    warmup: true,
  });
}
