import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

/**
 * Marketing homepage at `/`. Former `/workbench` redirects to the User portal.
 *
 * Named `proxy` rather than `middleware` because Next 16 renamed the convention;
 * a leftover `middleware.ts` is ignored at build time rather than reported, which
 * would take the homepage rewrite down silently.
 */
export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
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
  matcher: ["/", "/workbench", "/workbench/:path*"],
};
