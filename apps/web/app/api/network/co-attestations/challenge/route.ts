import { proxyJson } from "../../../../lib/backend";

export async function POST(request: Request) {
  const body = await request.text();
  return proxyJson("/v1/network/co-attestations/challenge", {
    method: "POST",
    body,
    headers: { "Content-Type": "application/json" },
    timeoutMs: 10_000,
  });
}
