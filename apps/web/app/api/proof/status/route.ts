import { proxyJson } from "../../../lib/backend";

export async function GET() {
  return proxyJson("/v1/proof/status", { timeoutMs: 8_000 });
}
