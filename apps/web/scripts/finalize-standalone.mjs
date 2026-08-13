/**
 * Complete the `output: "standalone"` bundle so it can actually be served.
 *
 * Next deliberately leaves `public/` and `.next/static/` out of the standalone
 * directory, expecting the deployment to copy them. Our Dockerfile does, but a
 * local `node .next/standalone/server.js` — which is what `next start` tells
 * you to run under this output mode — otherwise serves a site with a 404
 * homepage and no stylesheets or scripts at all. Copying them at the end of the
 * build makes every launch path serve the same complete site.
 */

import { cpSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = dirname(dirname(fileURLToPath(import.meta.url)));
const standalone = join(web, ".next", "standalone");

if (!existsSync(standalone)) {
  console.error(
    'finalize-standalone: .next/standalone is missing. Expected `output: "standalone"` in next.config.ts.',
  );
  process.exit(1);
}

for (const [from, to] of [
  [join(web, "public"), join(standalone, "public")],
  [join(web, ".next", "static"), join(standalone, ".next", "static")],
]) {
  if (!existsSync(from)) continue;
  mkdirSync(dirname(to), { recursive: true });
  cpSync(from, to, { recursive: true });
}

console.log("finalize-standalone: copied public/ and .next/static into .next/standalone");
