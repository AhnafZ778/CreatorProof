import { proxyJson } from "../../../lib/backend";

export async function GET(request: Request) {
  const input = new URL(request.url).searchParams;
  const query = new URLSearchParams();
  for (const key of ["limit", "offset"]) if (input.has(key)) query.set(key, input.get(key)!);
  return proxyJson(`/v1/admin/stored-cases?${query}`, { timeoutMs: 30_000 });
}
