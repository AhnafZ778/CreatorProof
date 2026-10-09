import { fetchBackend } from "../../../../../../lib/backend";

export async function GET(_request: Request, context: { params: Promise<{ scanId: string; kind: string }> }) {
  const { scanId, kind } = await context.params;
  if (!/^scn_[a-f0-9]{32}$/.test(scanId) || !["candidate", "reference"].includes(kind))
    return Response.json({ detail: "Invalid comparison" }, { status: 400 });
  try {
    const response = await fetchBackend(`/v1/admin/stored-cases/${scanId}/media/${kind}`, { redirect: "manual", timeoutMs: 30_000 });
    if (response.status >= 300 && response.status < 400) return Response.json({ detail: "Unexpected media redirect" }, { status: 502 });
    return new Response(response.body, { status: response.status, headers: {
      "Content-Type": response.headers.get("content-type") || "application/octet-stream",
      "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff",
    } });
  } catch { return Response.json({ detail: "Stored comparison unavailable" }, { status: 504 }); }
}
