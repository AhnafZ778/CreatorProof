import { NextResponse } from "next/server";

const backend = () => process.env.CREATORPROOF_API_URL ?? "http://localhost:8000";

export async function GET() {
  try {
    const response = await fetch(`${backend()}/healthz`, { cache: "no-store" });
    const body = await response.json();
    return NextResponse.json(body, { status: response.status });
  } catch {
    return NextResponse.json(
      { status: "unreachable", version: null, job_backend: null },
      { status: 503 },
    );
  }
}
