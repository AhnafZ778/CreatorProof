import { proxyJson } from "../../../lib/backend";

export async function GET(_request: Request, context: { params: Promise<{ caseId: string }> }) {
  const { caseId } = await context.params;
  return proxyJson(`/v1/review-cases/${encodeURIComponent(caseId)}`, { timeoutMs: 8_000 });
}
