import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

const appRoot = path.dirname(fileURLToPath(import.meta.url));

// In the pinned Next.js 16.3 runtime, devIndicators:false still displays an
// Issues badge for runtime/hydration errors. Disable the overlay UI itself;
// Next continues to collect and log errors through its development event bus.
if (process.env.NODE_ENV !== "production") {
  process.env.NEXT_PRIVATE_DISABLE_DEV_OVERLAY_UX = "1";
}

// Vercel compiles and hosts Next itself. `standalone` is the Docker/Render
// bundle; emitting it on Vercel makes `npm run build` look for a directory
// the platform never uses, then fail in finalize-standalone.mjs.
const nextConfig: NextConfig = {
  // A separate output directory lets browser checks run beside a developer's server.
  distDir: process.env.CREATORPROOF_WEB_DIST_DIR || ".next",
  ...(process.env.VERCEL === "1" ? {} : { output: "standalone" as const }),
  turbopack: {
    root: appRoot,
  },
  poweredByHeader: false,
  devIndicators: false,
  experimental: {
    // Proxy clones matched bodies. Keep its buffer below Vercel's 4.5 MB
    // function payload ceiling; route handlers reject oversized declarations.
    proxyClientMaxBodySize: 4_250_000,
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
      ...["/verify/:path*", "/api/public-verification/:path*"].map((source) => ({ source, headers: [{ key: "Referrer-Policy", value: "no-referrer" }, { key: "X-Robots-Tag", value: "noindex, nofollow" }, { key: "Cache-Control", value: "no-store" }] })),
    ];
  },
};

export default nextConfig;
