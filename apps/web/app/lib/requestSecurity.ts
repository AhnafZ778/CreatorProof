type RateEntry = { count: number; resetAt: number; lastSeen: number };
type RateStore = Map<string, RateEntry>;

const STORE_KEY = Symbol.for("creatorproof.web.rate-limit");
const MAX_RATE_KEYS = 2_000;

function rateStore(): RateStore {
  const target = globalThis as typeof globalThis & { [STORE_KEY]?: RateStore };
  target[STORE_KEY] ??= new Map();
  return target[STORE_KEY];
}

export function isTrustedMutationOrigin(
  request: Request,
  production = process.env.NODE_ENV === "production",
): boolean {
  const rawOrigin = request.headers.get("origin")?.trim();
  if (!rawOrigin) return !production;

  let origin: URL;
  let requestUrl: URL;
  try {
    origin = new URL(rawOrigin);
    requestUrl = new URL(request.url);
  } catch {
    return false;
  }
  if (!/^https?:$/.test(origin.protocol)) return false;

  // Next can reconstruct an absolute route URL from the configured listen
  // address rather than the authority used by the browser. In local
  // development that turns a real request to 127.0.0.1 into localhost; behind
  // a TLS-terminating proxy it can also turn the public HTTPS URL into an
  // internal HTTP URL. The Host header is the authority the browser actually
  // targeted, so use it with the proxy's public protocol when available.
  const forwardedProtocol = request.headers
    .get("x-forwarded-proto")
    ?.split(",", 1)[0]
    ?.trim()
    .toLowerCase();
  const protocol = forwardedProtocol === "http" || forwardedProtocol === "https"
    ? `${forwardedProtocol}:`
    : requestUrl.protocol;
  const host = request.headers.get("host")?.trim();

  const trustedOrigins = new Set([requestUrl.origin.toLowerCase()]);
  if (host) {
    try {
      trustedOrigins.add(new URL(`${protocol}//${host}`).origin.toLowerCase());
    } catch {
      return false;
    }
  }
  return trustedOrigins.has(origin.origin.toLowerCase());
}

function clientAddress(request: Request): string {
  return (
    request.headers.get("x-vercel-forwarded-for")?.split(",")[0]?.trim() ||
    request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    "unknown"
  );
}

function consumeRateLimit(
  key: string,
  limit: number,
  windowMs: number,
  now = Date.now(),
): { allowed: boolean; retryAfterSeconds: number } {
  const store = rateStore();
  if (store.size >= MAX_RATE_KEYS) {
    for (const [candidate, entry] of store) {
      if (entry.resetAt <= now) store.delete(candidate);
    }
    if (store.size >= MAX_RATE_KEYS) {
      const oldest = [...store.entries()].sort((a, b) => a[1].lastSeen - b[1].lastSeen)[0];
      if (oldest) store.delete(oldest[0]);
    }
  }

  const existing = store.get(key);
  if (!existing || existing.resetAt <= now) {
    store.set(key, { count: 1, resetAt: now + windowMs, lastSeen: now });
    return { allowed: true, retryAfterSeconds: 0 };
  }
  existing.lastSeen = now;
  if (existing.count >= limit) {
    return {
      allowed: false,
      retryAfterSeconds: Math.max(1, Math.ceil((existing.resetAt - now) / 1_000)),
    };
  }
  existing.count += 1;
  return { allowed: true, retryAfterSeconds: 0 };
}

/**
 * CSRF protection plus a bounded, best-effort per-instance limiter. The Render
 * tenant quota remains authoritative because Vercel instances do not share RAM.
 */
export function guardMutation(
  request: Request,
  options: { bucket: string; limit?: number; windowMs?: number },
): Response | null {
  if (!isTrustedMutationOrigin(request)) {
    return Response.json(
      { detail: "This mutation must originate from the CreatorProof web app.", error_code: "ORIGIN_DENIED" },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }

  const limit = consumeRateLimit(
    `${options.bucket}:${clientAddress(request)}`,
    options.limit ?? 20,
    options.windowMs ?? 60_000,
  );
  if (limit.allowed) return null;
  return Response.json(
    { detail: "Too many requests. Wait briefly and retry.", error_code: "WEB_RATE_LIMITED" },
    {
      status: 429,
      headers: {
        "Cache-Control": "no-store",
        "Retry-After": String(limit.retryAfterSeconds),
      },
    },
  );
}
