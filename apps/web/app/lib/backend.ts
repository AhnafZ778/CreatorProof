import { NextResponse } from "next/server";

export const backendUrl = () => process.env.CREATORPROOF_API_URL ?? "http://localhost:8000";
export const backendKey = () =>
  process.env.CREATORPROOF_DEV_API_KEY ?? "change-me-before-sharing";

type ProxyOptions = {
  method?: string;
  body?: BodyInit | null;
  timeoutMs?: number;
  headers?: Record<string, string>;
};

/**
 * Forward a request to the API and preserve its status. The browser never holds
 * an API key: every call goes through the Next server, which is the only place
 * the credential exists.
 */
export async function proxyJson(path: string, options: ProxyOptions = {}) {
  const { method = "GET", body = null, timeoutMs = 10_000, headers = {} } = options;
  try {
    const response = await fetch(`${backendUrl()}${path}`, {
      method,
      headers: { "X-API-Key": backendKey(), ...headers },
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
    const text = await response.text();
    const parsed = text ? JSON.parse(text) : null;
    return NextResponse.json(parsed, { status: response.status });
  } catch (caught) {
    const timedOut = caught instanceof Error && caught.name === "TimeoutError";
    return NextResponse.json(
      {
        detail: timedOut
          ? "The API did not respond in time."
          : "The API is unreachable from this console.",
        error_code: timedOut ? "BACKEND_TIMEOUT" : "BACKEND_UNREACHABLE",
      },
      { status: 504 },
    );
  }
}
