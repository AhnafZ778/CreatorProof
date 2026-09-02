import { NextResponse } from "next/server";

import { backendAttemptTimeout } from "./backendTiming";
import { readBackendConfig, ServerConfigurationError } from "./serverEnv";

type ProxyOptions = {
  method?: string;
  body?: BodyInit | null;
  timeoutMs?: number;
  headers?: Record<string, string>;
  /** Only enable replay when the operation is naturally or explicitly idempotent. */
  retry?: boolean;
  /** Wake a sleeping Render service before sending a non-replayable mutation. */
  warmup?: boolean;
};

type BackendFetchOptions = ProxyOptions & {
  includeApiKey?: boolean;
  redirect?: RequestRedirect;
};

const RETRYABLE_STATUSES = new Set([502, 503, 504]);
const READY_CACHE_MS = 30_000;
let lastReadyAt = 0;

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function retryDelay(attempt: number): number {
  return Math.min(4_000, 500 * 2 ** Math.max(0, attempt - 1));
}

function backendEndpoint(path: string): string {
  if (!path.startsWith("/")) throw new Error("Backend paths must start with '/'.");
  const { apiUrl } = readBackendConfig();
  return `${apiUrl}${path}`;
}

function shouldRetry(method: string, explicitlyRetryable: boolean | undefined): boolean {
  return explicitlyRetryable ?? (method === "GET" || method === "HEAD");
}

/**
 * Fetch the Render API within one overall deadline. Short attempts keep poking a
 * sleeping free service; once it wakes, the successful response is returned.
 */
export async function fetchBackend(
  path: string,
  options: BackendFetchOptions = {},
): Promise<Response> {
  const config = readBackendConfig();
  const {
    method = "GET",
    body = null,
    timeoutMs = config.coldStartBudgetMs,
    headers = {},
    includeApiKey = true,
    redirect = "follow",
  } = options;
  const normalizedMethod = method.toUpperCase();
  const retryable = shouldRetry(normalizedMethod, options.retry);
  const startedAt = Date.now();
  let attempt = 0;
  let lastResponse: Response | null = null;
  let lastError: unknown = null;

  while (Date.now() - startedAt < timeoutMs) {
    attempt += 1;
    const remaining = timeoutMs - (Date.now() - startedAt);
    // Only read-only requests use short attempts to keep nudging a sleeping
    // Render service. Mutations are warmed first and get the full remaining
    // budget: aborting a valid 20-second registration after 12 seconds would
    // overlap it with its own retry before the first transaction commits.
    const attemptTimeout = backendAttemptTimeout(normalizedMethod, retryable, remaining);
    try {
      const response = await fetch(backendEndpoint(path), {
        method,
        headers: {
          ...(includeApiKey ? { "X-API-Key": config.apiKey } : {}),
          ...headers,
        },
        body,
        cache: "no-store",
        redirect,
        signal: AbortSignal.timeout(attemptTimeout),
      });
      lastResponse = response;
      if (!retryable || !RETRYABLE_STATUSES.has(response.status)) {
        if (response.status < 500) lastReadyAt = Date.now();
        return response;
      }
      await response.body?.cancel();
    } catch (caught) {
      lastError = caught;
      if (!retryable) throw caught;
    }

    const wait = retryDelay(attempt);
    if (Date.now() - startedAt + wait >= timeoutMs) break;
    await delay(wait);
  }

  if (lastResponse) return lastResponse;
  if (lastError instanceof Error) throw lastError;
  throw new DOMException("The backend request timed out.", "TimeoutError");
}

/**
 * A health request is safe to retry and prevents replaying a work registration
 * merely because Render was still waking after the browser uploaded the file.
 */
export async function warmBackend(timeoutMs?: number): Promise<void> {
  if (Date.now() - lastReadyAt < READY_CACHE_MS) return;
  const config = readBackendConfig();
  const response = await fetchBackend("/healthz", {
    timeoutMs: timeoutMs ?? config.coldStartBudgetMs,
    retry: true,
    includeApiKey: false,
  });
  if (!response.ok) {
    throw new Error(`Backend readiness returned ${response.status}.`);
  }
  lastReadyAt = Date.now();
}

function upstreamErrorResponse(status: number) {
  return NextResponse.json(
    {
      detail: "The backend returned a response that the web gateway could not read.",
      error_code: "BACKEND_RESPONSE_INVALID",
    },
    { status: status >= 400 ? status : 502, headers: { "Cache-Control": "no-store" } },
  );
}

function unavailableResponse(caught: unknown) {
  const timedOut =
    caught instanceof Error &&
    (caught.name === "TimeoutError" || caught.name === "AbortError");
  const configuration = caught instanceof ServerConfigurationError;
  if (configuration) console.error(caught.message);
  return NextResponse.json(
    {
      detail: configuration
        ? "The web deployment is missing required server configuration."
        : timedOut
          ? "The backend is still waking or did not respond before the gateway deadline."
          : "The backend is temporarily unreachable from the web deployment.",
      error_code: configuration
        ? caught.code
        : timedOut
          ? "BACKEND_TIMEOUT"
          : "BACKEND_UNREACHABLE",
    },
    {
      status: configuration ? 503 : 504,
      headers: { "Cache-Control": "no-store", "Retry-After": "3" },
    },
  );
}

/**
 * Forward JSON while keeping the API key exclusively in the Vercel runtime.
 * Mutations can warm Render first; only explicitly idempotent ones are replayed.
 */
export async function proxyJson(path: string, options: ProxyOptions = {}) {
  try {
    const overallTimeoutMs = options.timeoutMs ?? readBackendConfig().coldStartBudgetMs;
    const startedAt = Date.now();
    if (options.warmup) {
      await warmBackend(Math.min(overallTimeoutMs, 75_000));
    }
    const remaining = overallTimeoutMs - (Date.now() - startedAt);
    if (remaining <= 0) throw new DOMException("The backend did not become ready.", "TimeoutError");
    const response = await fetchBackend(path, { ...options, timeoutMs: remaining });
    const text = await response.text();
    if (!text) {
      return new NextResponse(null, {
        status: response.status,
        headers: { "Cache-Control": "no-store" },
      });
    }
    try {
      return NextResponse.json(JSON.parse(text), {
        status: response.status,
        headers: { "Cache-Control": "no-store" },
      });
    } catch {
      return upstreamErrorResponse(response.status);
    }
  } catch (caught) {
    return unavailableResponse(caught);
  }
}
