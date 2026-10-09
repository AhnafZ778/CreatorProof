import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

import { readWebAuthConfig, ServerConfigurationError } from "./app/lib/serverEnv";
import { isPublicVerificationApiPath } from "./app/lib/phase1Contract";

function constantTimeEqual(left: string, right: string): boolean {
  const encoder = new TextEncoder();
  const a = encoder.encode(left);
  const b = encoder.encode(right);
  const length = Math.max(a.length, b.length);
  let mismatch = a.length ^ b.length;
  for (let index = 0; index < length; index += 1) {
    mismatch |= (a[index] ?? 0) ^ (b[index] ?? 0);
  }
  return mismatch === 0;
}

function basicCredentials(request: NextRequest): { username: string; password: string } | null {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Basic ")) return null;
  try {
    const decoded = atob(authorization.slice(6));
    const separator = decoded.indexOf(":");
    if (separator < 0) return null;
    return { username: decoded.slice(0, separator), password: decoded.slice(separator + 1) };
  } catch {
    return null;
  }
}

function authenticationResponse() {
  return new NextResponse("Authentication required", {
    status: 401,
    headers: {
      "Cache-Control": "no-store",
      "Content-Type": "text/plain; charset=utf-8",
      "WWW-Authenticate": 'Basic realm="CreatorProof", charset="UTF-8"',
    },
  });
}

function protectedPath(pathname: string): boolean {
  if (isPublicVerificationApiPath(pathname)) return false;
  return (
    pathname === "/admin" ||
    pathname.startsWith("/admin/") ||
    pathname === "/artist" ||
    pathname.startsWith("/artist/") ||
    pathname === "/user" ||
    pathname.startsWith("/user/") ||
    pathname === "/api" ||
    pathname.startsWith("/api/")
  );
}

/**
 * Marketing homepage at `/`. Former `/workbench` redirects to the User portal.
 *
 * Named `proxy` rather than `middleware` because Next 16 renamed the convention;
 * a leftover `middleware.ts` is ignored at build time rather than reported, which
 * would take the homepage rewrite down silently.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (protectedPath(pathname)) {
    try {
      const authentication = readWebAuthConfig();
      if (authentication.mode === "basic") {
        const credentials = basicCredentials(request);
        if (
          !credentials ||
          !constantTimeEqual(credentials.username, authentication.username) ||
          !constantTimeEqual(credentials.password, authentication.password)
        ) {
          return authenticationResponse();
        }
      }
    } catch (caught) {
      if (caught instanceof ServerConfigurationError) console.error(caught.message);
      return NextResponse.json(
        { detail: "The web deployment is missing required authentication configuration." },
        { status: 503, headers: { "Cache-Control": "no-store" } },
      );
    }
  }
  if (pathname === "/") {
    return NextResponse.rewrite(new URL("/landing.html", request.url));
  }
  if (pathname === "/workbench" || pathname.startsWith("/workbench/")) {
    const url = request.nextUrl.clone();
    url.pathname = "/user";
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    "/",
    "/artist/:path*",
    "/admin/:path*",
    "/user/:path*",
    "/api/:path*",
    "/workbench",
    "/workbench/:path*",
  ],
};
