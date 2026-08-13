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
