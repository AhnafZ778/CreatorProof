import { NextResponse } from "next/server";

const backend = () => process.env.CREATORPROOF_API_URL ?? "http://localhost:8000";
const apiKey = () => process.env.CREATORPROOF_DEV_API_KEY ?? "change-me-before-sharing";
export const maxDuration = 40;

export async function POST(request: Request) {
  const form = await request.formData();
  const idempotency = request.headers.get("Idempotency-Key") ?? crypto.randomUUID();
  try {
    const response = await fetch(`${backend()}/v1/scans`, {
      method: "POST",
      headers: { "X-API-Key": apiKey(), "Idempotency-Key": idempotency },
      body: form,
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json(
      {
        detail: "The API did not accept the scan in time. Confirm that the local or Redis job backend is active.",
        error_code: "SCAN_ACCEPT_TIMEOUT",
      },
      { status: 504 },
    );
  }
}
