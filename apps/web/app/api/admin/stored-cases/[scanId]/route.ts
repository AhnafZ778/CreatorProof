import { proxyJson } from "../../../../lib/backend";
import { guardMutation } from "../../../../lib/requestSecurity";

type Context = { params: Promise<{ scanId: string }> };
async function mutate(request: Request, context: Context, method: "POST" | "DELETE") {
  const denied = guardMutation(request, { bucket: "stored-comparison", limit: 30 });
  if (denied) return denied;
  const { scanId } = await context.params;
  if (!/^scn_[a-f0-9]{32}$/.test(scanId)) return Response.json({ detail: "Invalid scan" }, { status: 400 });
  return proxyJson(`/v1/admin/stored-cases/${scanId}`, { method, retry: false, timeoutMs: 30_000 });
}
export function POST(request: Request, context: Context) { return mutate(request, context, "POST"); }
export function DELETE(request: Request, context: Context) { return mutate(request, context, "DELETE"); }
