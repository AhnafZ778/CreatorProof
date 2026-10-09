import { proxyJson } from "../../../../../lib/backend";
import { guardMutation } from "../../../../../lib/requestSecurity";

export async function POST(request: Request, context: { params: Promise<{ scanId: string }> }) {
  const denied = guardMutation(request, { bucket: "admin-open-review", limit: 20 });
  if (denied) return denied;
  const { scanId } = await context.params;
  if (!/^scn_[a-f0-9]{32}$/.test(scanId)) return Response.json({ detail: "Invalid scan identifier." }, { status: 400 });
  return proxyJson(`/v1/admin/user-detections/${encodeURIComponent(scanId)}/review-case`, {
    method: "POST", body: "{}", headers: { "Content-Type": "application/json" }, retry: false,
  });
}
