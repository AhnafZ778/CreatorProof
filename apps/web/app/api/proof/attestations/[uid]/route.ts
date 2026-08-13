import { proxyJson } from "../../../../lib/backend";

const SHA256_PATTERN = /^(?:0x)?[0-9a-fA-F]{64}$/;

export async function GET(request: Request, context: { params: Promise<{ uid: string }> }) {
  const { uid } = await context.params;
  const expectedPacketHash = new URL(request.url).searchParams.get(
    "expected_packet_hash_sha256",
  );
  if (expectedPacketHash && !SHA256_PATTERN.test(expectedPacketHash)) {
    return Response.json(
      { detail: "expected_packet_hash_sha256 must be a 32-byte hexadecimal SHA-256 value" },
      { status: 400 },
    );
  }
  const query = expectedPacketHash
    ? `?expected_packet_hash_sha256=${encodeURIComponent(expectedPacketHash)}`
    : "";
  return proxyJson(`/v1/proof/attestations/${encodeURIComponent(uid)}${query}`, {
    timeoutMs: 20_000,
  });
}
