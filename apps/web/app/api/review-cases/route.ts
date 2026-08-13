import { proxyJson } from "../../lib/backend";

export async function GET(request: Request) {
  const query = new URL(request.url).search;
  return proxyJson(`/v1/review-cases${query}`, { timeoutMs: 8_000 });
}
