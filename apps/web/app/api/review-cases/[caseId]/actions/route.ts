import { proxyJson } from "../../../../lib/backend";

export async function POST(request: Request, context: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await context.params;
  const body = await request.text();
  return proxyJson(`/v1/review-cases/${encodeURIComponent(caseId)}/actions`, {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
    timeoutMs: 8_000,
  });
}
