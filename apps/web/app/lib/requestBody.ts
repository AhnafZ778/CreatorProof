import {
  ALLOWED_IMAGE_TYPES,
  MAX_IMAGE_UPLOAD_BYTES,
  MAX_JSON_REQUEST_BYTES,
  MAX_PROXY_REQUEST_BYTES,
} from "./deployment.ts";

export class RequestInputError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(
    status: number,
    code: string,
    message: string,
  ) {
    super(message);
    this.name = "RequestInputError";
    this.status = status;
    this.code = code;
  }
}

function contentLength(request: Request): number | null {
  const raw = request.headers.get("content-length");
  if (!raw) return null;
  const parsed = Number(raw);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : null;
}

function requireBoundedBody(request: Request, maximum: number, requireLength: boolean): void {
  const length = contentLength(request);
  if (length === null && requireLength && process.env.NODE_ENV === "production") {
    throw new RequestInputError(411, "CONTENT_LENGTH_REQUIRED", "A Content-Length header is required.");
  }
  if (length !== null && length > maximum) {
    throw new RequestInputError(413, "REQUEST_TOO_LARGE", "The request is too large.");
  }
}

export async function readJsonObject(
  request: Request,
  maximum = MAX_JSON_REQUEST_BYTES,
): Promise<Record<string, unknown>> {
  requireBoundedBody(request, maximum, false);
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > maximum) {
    throw new RequestInputError(413, "REQUEST_TOO_LARGE", "The JSON request is too large.");
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new RequestInputError(400, "INVALID_JSON", "The request body must be valid JSON.");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new RequestInputError(400, "INVALID_JSON_OBJECT", "The request body must be a JSON object.");
  }
  return parsed as Record<string, unknown>;
}

export async function readBoundedText(
  request: Request,
  maximum = MAX_JSON_REQUEST_BYTES,
): Promise<string> {
  requireBoundedBody(request, maximum, false);
  const text = await request.text();
  if (new TextEncoder().encode(text).byteLength > maximum) {
    throw new RequestInputError(413, "REQUEST_TOO_LARGE", "The request is too large.");
  }
  return text;
}

export async function readImageForm(request: Request): Promise<FormData> {
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("multipart/form-data")) {
    throw new RequestInputError(415, "MULTIPART_REQUIRED", "Expected a multipart image upload.");
  }
  requireBoundedBody(request, MAX_PROXY_REQUEST_BYTES, true);
  const form = await request.formData();
  const file = form.get("file");
  if (!(file instanceof File) || file.size <= 0) {
    throw new RequestInputError(400, "IMAGE_REQUIRED", "Choose an image file.");
  }
  if (file.size > MAX_IMAGE_UPLOAD_BYTES) {
    throw new RequestInputError(413, "IMAGE_TOO_LARGE", "The image exceeds the 4 MB deployment limit.");
  }
  if (!ALLOWED_IMAGE_TYPES.has(file.type.toLowerCase())) {
    throw new RequestInputError(415, "IMAGE_TYPE_UNSUPPORTED", "Use a PNG, JPEG, or WebP image.");
  }
  return form;
}

export function requestInputErrorResponse(caught: unknown): Response | null {
  if (!(caught instanceof RequestInputError)) return null;
  return Response.json(
    { detail: caught.message, error_code: caught.code },
    { status: caught.status, headers: { "Cache-Control": "no-store" } },
  );
}
