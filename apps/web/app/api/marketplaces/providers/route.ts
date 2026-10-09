import { proxyJson } from "../../../lib/backend";

export async function GET() {
  return proxyJson("/v1/marketplaces/providers", { timeoutMs: 15_000, retry: false });
}
