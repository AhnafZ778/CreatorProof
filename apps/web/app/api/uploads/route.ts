import { proxyJson } from "../../lib/backend";
import { ALLOWED_IMAGE_TYPES, MAX_IMAGE_UPLOAD_BYTES } from "../../lib/deployment";
import { readJsonObject, requestInputErrorResponse } from "../../lib/requestBody";
import { guardMutation } from "../../lib/requestSecurity";
import { readBackendConfig } from "../../lib/serverEnv";

export const maxDuration = 60;

export async function POST(request: Request) {
  const denied = guardMutation(request, { bucket: "upload-grant", limit: 12 });
  if (denied) return denied;

  try {
    if (!readBackendConfig().directUploadEnabled) {
      return Response.json(
        { detail: "Direct object upload is disabled.", error_code: "DIRECT_UPLOAD_DISABLED" },
        { status: 503, headers: { "Cache-Control": "no-store" } },
      );
    }
    const input = await readJsonObject(request);
    const purpose = input.purpose;
    const filename = input.filename;
    const contentType = input.content_type;
    const sizeBytes = input.size_bytes;
    if (purpose !== "scan" && purpose !== "work") {
      return Response.json(
        { detail: "purpose must be scan or work.", error_code: "UPLOAD_PURPOSE_INVALID" },
        { status: 400 },
      );
    }
    if (
      typeof filename !== "string" ||
      !filename.trim() ||
      filename.length > 255 ||
      /[\0/\\]/.test(filename)
    ) {
      return Response.json(
        { detail: "filename is invalid.", error_code: "UPLOAD_FILENAME_INVALID" },
        { status: 400 },
      );
    }
    if (typeof contentType !== "string" || !ALLOWED_IMAGE_TYPES.has(contentType.toLowerCase())) {
      return Response.json(
        { detail: "Use a PNG, JPEG, or WebP image.", error_code: "IMAGE_TYPE_UNSUPPORTED" },
        { status: 415 },
      );
    }
    if (
      typeof sizeBytes !== "number" ||
      !Number.isSafeInteger(sizeBytes) ||
      sizeBytes <= 0 ||
      sizeBytes > MAX_IMAGE_UPLOAD_BYTES
    ) {
      return Response.json(
        { detail: "The image must be non-empty and no larger than 4 MB.", error_code: "IMAGE_TOO_LARGE" },
        { status: 413 },
      );
    }

    return proxyJson("/v1/uploads", {
      method: "POST",
      body: JSON.stringify({
        purpose,
        filename,
        content_type: contentType.toLowerCase(),
        size_bytes: sizeBytes,
      }),
      headers: { "Content-Type": "application/json" },
      timeoutMs: 90_000,
      retry: true,
      warmup: true,
    });
  } catch (caught) {
    return requestInputErrorResponse(caught) ?? Response.json(
      { detail: "The upload grant could not be created.", error_code: "UPLOAD_GRANT_FAILED" },
      { status: 503 },
    );
  }
}
