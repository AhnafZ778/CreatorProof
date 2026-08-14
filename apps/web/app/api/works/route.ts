import { proxyJson } from "../../lib/backend";

// Origin screening on enrollment can run OCR, C2PA, and the synthetic ensemble
// before the API writes a row. The proxy has to wait at least as long as that
// work, or the browser sees a timeout while the catalog is still being decided.
export const maxDuration = 180;

export async function POST(request: Request) {
  const form = await request.formData();
  return proxyJson("/v1/works", {
    method: "POST",
    body: form,
    timeoutMs: 150_000,
  });
}

/**
 * List what a catalog actually holds. A scan can only find what was registered,
 * so the scan desk reads this before running to tell the operator whether the
 * catalog they typed has anything in it to match against.
 */
export async function GET(request: Request) {
  const catalogId = new URL(request.url).searchParams.get("catalog_id");
  const query = catalogId ? `?catalog_id=${encodeURIComponent(catalogId)}` : "";
  return proxyJson(`/v1/works${query}`);
}
