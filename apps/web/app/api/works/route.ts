import { NextResponse } from "next/server";

function backend() {
  return process.env.CREATORPROOF_API_URL ?? "http://localhost:8000";
}

function apiKey() {
  return process.env.CREATORPROOF_DEV_API_KEY ?? "change-me-before-sharing";
}

export async function POST(request: Request) {
  const form = await request.formData();
  const response = await fetch(`${backend()}/v1/works`, {
    method: "POST",
    headers: { "X-API-Key": apiKey() },
    body: form,
    cache: "no-store",
  });
  const body = await response.json();
  return NextResponse.json(body, { status: response.status });
}

