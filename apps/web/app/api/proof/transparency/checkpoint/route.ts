import { proxyJson } from "../../../../lib/backend";

export async function GET() {
  return proxyJson("/v1/proof/transparency/checkpoint", { timeoutMs: 8_000 });
}
