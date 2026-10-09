import { fetchBackend } from "@/app/lib/backend";
import { validPublicToken } from "@/app/lib/phase1Contract";

export async function GET(_request: Request, { params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const headers = { "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff" };
  if (!validPublicToken(token)) return Response.json({ detail: "Verification link not found." }, { status: 404, headers });
  try {
    const response = await fetchBackend(`/verify/${token}`, { includeApiKey: false, retry: false, redirect: "error", timeoutMs: 30000 });
    const body: unknown = await response.json();
    return Response.json(body, { status: response.status, headers });
  } catch {
    return Response.json({ detail: "Verification is temporarily unavailable. Please retry." }, { status: 503, headers });
  }
}
