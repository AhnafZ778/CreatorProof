import { fetchBackend } from "../../../../lib/backend";

export async function GET(
  _request: Request,
  context: { params: Promise<{ scanId: string }> },
) {
  const { scanId } = await context.params;
  try {
    const response = await fetchBackend(
      `/v1/scans/${encodeURIComponent(scanId)}/media`,
      { timeoutMs: 75_000, redirect: "manual" },
    );
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location");
      if (!location)
        return Response.json(
          { detail: "The media redirect was incomplete." },
          { status: 502 },
        );
      const destination = new URL(location);
      if (destination.protocol !== "https:")
        return Response.json(
          { detail: "The media redirect was not secure." },
          { status: 502 },
        );
      return new Response(null, {
        status: 307,
        headers: {
          Location: destination.toString(),
          "Cache-Control": "private, no-store",
        },
      });
    }
    const headers = new Headers({
      "Content-Type":
        response.headers.get("content-type") ?? "application/octet-stream",
      "Cache-Control": "private, max-age=300",
    });
    const length = response.headers.get("content-length");
    if (length) headers.set("Content-Length", length);
    return new Response(response.body, { status: response.status, headers });
  } catch {
    return Response.json(
      { detail: "Submitted media is temporarily unavailable." },
      { status: 504 },
    );
  }
}
