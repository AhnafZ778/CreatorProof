import { fetchBackend } from "../../../../lib/backend";

export async function GET(
  _request: Request,
  context: { params: Promise<{ workId: string }> },
) {
  const { workId } = await context.params;
  try {
    const response = await fetchBackend(
      `/v1/works/${encodeURIComponent(workId)}/media`,
      { timeoutMs: 75_000, redirect: "manual" },
    );
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location");
      if (!location) {
        return Response.json(
          { detail: "The media redirect was incomplete.", error_code: "MEDIA_REDIRECT_INVALID" },
          { status: 502 },
        );
      }
      let destination: URL;
      try {
        destination = new URL(location);
      } catch {
        return Response.json(
          { detail: "The media redirect was invalid.", error_code: "MEDIA_REDIRECT_INVALID" },
          { status: 502 },
        );
      }
      if (destination.protocol !== "https:") {
        return Response.json(
          { detail: "The media redirect was not secure.", error_code: "MEDIA_REDIRECT_INSECURE" },
          { status: 502 },
        );
      }
      return new Response(null, {
        status: 307,
        headers: {
          Location: destination.toString(),
          "Cache-Control": "private, no-store",
          "Referrer-Policy": "no-referrer",
        },
      });
    }
    const responseHeaders = new Headers({
      "Content-Type": response.headers.get("content-type") ?? "application/octet-stream",
      "Cache-Control": "private, max-age=300",
    });
    const contentLength = response.headers.get("content-length");
    if (contentLength) responseHeaders.set("Content-Length", contentLength);
    return new Response(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      { detail: "Reference media is temporarily unavailable.", error_code: "MEDIA_UNAVAILABLE" },
      { status: 504 },
    );
  }
}
