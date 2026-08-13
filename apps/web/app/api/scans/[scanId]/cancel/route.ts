import { proxyJson } from "../../../../lib/backend";

export async function POST(request: Request, context: { params: Promise<{ scanId: string }> }) {
  const { scanId } = await context.params;
  const body = await request.text();
  return proxyJson(`/v1/scans/${encodeURIComponent(scanId)}/cancel`, {
    method: "POST",
    body: body || JSON.stringify({ reason: "Cancelled from the console" }),
    headers: { "Content-Type": "application/json" },
    timeoutMs: 8_000,
  });
}
