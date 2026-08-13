import { proxyJson } from "../../../lib/backend";

export async function GET(request: Request) {
  const scanId = new URL(request.url).searchParams.get("scan_id");
  const query = scanId ? `?scan_id=${encodeURIComponent(scanId)}` : "";
  return proxyJson(`/v1/network/co-attestations${query}`, { timeoutMs: 8_000 });
}

export async function POST(request: Request) {
  const body = await request.text();
  return proxyJson("/v1/network/co-attestations", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
    timeoutMs: 15_000,
  });
}
