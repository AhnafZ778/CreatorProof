import { NextResponse } from "next/server";

const backend = () => process.env.CREATORPROOF_API_URL ?? "http://localhost:8000";
const apiKey = () => process.env.CREATORPROOF_DEV_API_KEY ?? "change-me-before-sharing";

export async function GET(
  _request: Request,
  context: { params: Promise<{ scanId: string }> },
) {
  const { scanId } = await context.params;
  try {
    const response = await fetch(`${backend()}/v1/scans/${encodeURIComponent(scanId)}`, {
      headers: { "X-API-Key": apiKey() },
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json(
      { detail: "Progress is temporarily unavailable.", error_code: "SCAN_POLL_TIMEOUT" },
      { status: 504 },
    );
  }
}
