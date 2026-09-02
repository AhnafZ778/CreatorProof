import { proxyJson } from "../../../lib/backend";

export async function GET() {
  return proxyJson("/v1/network/status", { timeoutMs: 75_000 });
}
