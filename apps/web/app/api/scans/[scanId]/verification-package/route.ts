import { proxyJson } from "../../../../lib/backend";

export async function GET(_request: Request, context: { params: Promise<{ scanId: string }> }) {
  const { scanId } = await context.params;
  return proxyJson(`/v1/scans/${encodeURIComponent(scanId)}/verification-package`, {
    timeoutMs: 15_000,
  });
}
