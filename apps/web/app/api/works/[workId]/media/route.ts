const backend = () => process.env.CREATORPROOF_API_URL ?? "http://localhost:8000";
const apiKey = () => process.env.CREATORPROOF_DEV_API_KEY ?? "change-me-before-sharing";

export async function GET(
  _request: Request,
  context: { params: Promise<{ workId: string }> },
) {
  const { workId } = await context.params;
  const response = await fetch(
    `${backend()}/v1/works/${encodeURIComponent(workId)}/media`,
    {
      headers: { "X-API-Key": apiKey() },
      cache: "no-store",
    },
  );
  const body = await response.arrayBuffer();
  return new Response(body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/octet-stream",
      "Cache-Control": "private, max-age=300",
    },
  });
}
