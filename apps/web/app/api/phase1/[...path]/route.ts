import { fetchBackend, proxyJson } from "@/app/lib/backend";
import { phase1Route } from "@/app/lib/phase1Contract";
import { readJsonObject, requestInputErrorResponse } from "@/app/lib/requestBody";
import { guardMutation } from "@/app/lib/requestSecurity";

export const maxDuration = 60;
type Context = { params: Promise<{ path: string[] }> };
async function handle(request: Request, context: Context) {
  const { path } = await context.params;
  const target = phase1Route(path, request.method);
  if (!target) return Response.json({ detail: "This operation is not available." }, { status: 404 });
  if (request.method !== "GET") {
    const denied = guardMutation(request, { bucket: "phase1-write", limit: 30 });
    if (denied) return denied;
  }
  try {
    const body = request.method === "POST" ? JSON.stringify(await readJsonObject(request, 65536)) : undefined;
    if (request.method === "GET" && /\/(?:ai\.txt|rights-statement)$/.test(target)) {
      const response = await fetchBackend(target, { redirect: "error" });
      return new Response(await response.text(), { status: response.status, headers: { "Content-Type": response.ok ? "text/plain; charset=utf-8" : "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" } });
    }
    return proxyJson(target, { method: request.method, body, headers: body ? { "Content-Type": "application/json" } : {}, retry: request.method === "GET", warmup: request.method === "POST", redirect: "error" });
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json({ detail: "The service is unavailable. Please retry." }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
export const GET = handle;
export const POST = handle;
export const DELETE = handle;
