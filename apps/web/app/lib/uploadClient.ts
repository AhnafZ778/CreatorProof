"use client";

import {
  MAX_IMAGE_PIXELS,
  MAX_IMAGE_UPLOAD_BYTES,
  validateImageMetadata,
} from "./deployment";

type UploadPurpose = "scan" | "work";

type PresignedUpload = {
  method: "PUT";
  url: string;
  headers: Record<string, string>;
  expires_seconds: number;
  max_bytes: number;
};

type UploadGrant = {
  upload_token: string;
  upload: PresignedUpload;
};

export class UploadValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UploadValidationError";
  }
}

function isUploadGrant(value: unknown): value is UploadGrant {
  if (!value || typeof value !== "object") return false;
  const grant = value as Partial<UploadGrant>;
  const upload = grant.upload as Partial<PresignedUpload> | undefined;
  return Boolean(
    typeof grant.upload_token === "string" &&
      grant.upload_token &&
      upload &&
      upload.method === "PUT" &&
      typeof upload.url === "string" &&
      upload.url.startsWith("https://") &&
      upload.headers &&
      typeof upload.headers === "object" &&
      Object.values(upload.headers).every((value) => typeof value === "string") &&
      typeof upload.max_bytes === "number" &&
      Number.isSafeInteger(upload.max_bytes) &&
      upload.max_bytes > 0 &&
      typeof upload.expires_seconds === "number" &&
      upload.expires_seconds > 0,
  );
}

async function validateImageDimensions(file: File): Promise<void> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new UploadValidationError("The selected file could not be decoded as an image.");
  }
  try {
    if (bitmap.width * bitmap.height > MAX_IMAGE_PIXELS) {
      throw new UploadValidationError(
        "Images may contain at most 6 megapixels on this deployment. Resize the image and retry.",
      );
    }
  } finally {
    bitmap.close();
  }
}

export async function validateImageFile(file: File): Promise<void> {
  const metadataError = validateImageMetadata(file);
  if (metadataError) throw new UploadValidationError(metadataError);
  await validateImageDimensions(file);
}

function textFields(form: FormData): Record<string, string | string[]> {
  const fields: Record<string, string | string[]> = {};
  for (const [key, value] of form.entries()) {
    if (value instanceof File) continue;
    const existing = fields[key];
    if (existing === undefined) fields[key] = value;
    else if (Array.isArray(existing)) existing.push(value);
    else fields[key] = [existing, value];
  }
  return fields;
}

async function directUpload(
  endpoint: string,
  purpose: UploadPurpose,
  file: File,
  form: FormData,
  headers: Record<string, string>,
): Promise<Response | null> {
  const grantResponse = await fetch("/api/uploads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      purpose,
      filename: file.name,
      content_type: file.type,
      size_bytes: file.size,
    }),
    signal: AbortSignal.timeout(90_000),
  });
  if (grantResponse.status === 404 || grantResponse.status === 501 || grantResponse.status === 503) {
    await grantResponse.body?.cancel();
    return null;
  }
  const grantText = await grantResponse.text();
  let grantBody: unknown = null;
  try {
    grantBody = grantText ? JSON.parse(grantText) : null;
  } catch {
    // The shape check below turns an invalid success body into a gateway error.
  }
  if (!grantResponse.ok) {
    return new Response(grantText, {
      status: grantResponse.status,
      headers: { "Content-Type": grantResponse.headers.get("content-type") ?? "application/json" },
    });
  }
  if (!isUploadGrant(grantBody)) {
    throw new Error("The upload service returned an invalid grant.");
  }
  if (file.size > grantBody.upload.max_bytes || file.size > MAX_IMAGE_UPLOAD_BYTES) {
    throw new UploadValidationError("The image is larger than the upload grant permits.");
  }

  const putResponse = await fetch(grantBody.upload.url, {
    method: "PUT",
    headers: grantBody.upload.headers,
    body: file,
    signal: AbortSignal.timeout(90_000),
  });
  if (!putResponse.ok) {
    throw new Error(`Object upload failed (${putResponse.status}).`);
  }

  return fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: JSON.stringify({ ...textFields(form), upload_token: grantBody.upload_token }),
    signal: AbortSignal.timeout(180_000),
  });
}

/**
 * Prefer S3/R2 direct upload so bytes do not traverse a Vercel Function. If the
 * backend deliberately has direct upload disabled, the small bounded multipart
 * route remains available for local development and compatibility.
 */
export async function submitImageForm(options: {
  endpoint: string;
  purpose: UploadPurpose;
  form: FormData;
  headers?: Record<string, string>;
}): Promise<Response> {
  const file = options.form.get("file");
  if (!(file instanceof File)) throw new UploadValidationError("Choose an image file.");
  await validateImageFile(file);

  const headers = options.headers ?? {};
  const direct = await directUpload(options.endpoint, options.purpose, file, options.form, headers);
  if (direct) return direct;
  if (file.size > MAX_IMAGE_UPLOAD_BYTES) {
    throw new UploadValidationError("Direct upload is unavailable and the image is too large.");
  }
  return fetch(options.endpoint, {
    method: "POST",
    headers,
    body: options.form,
    signal: AbortSignal.timeout(180_000),
  });
}
