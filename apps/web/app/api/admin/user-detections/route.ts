import { proxyJson } from "../../../lib/backend";

export async function GET(request: Request) {
  const query = new URL(request.url).search || "?limit=100";
  return proxyJson(`/v1/admin/user-detections${query}`, { timeoutMs: 75_000 });
}
