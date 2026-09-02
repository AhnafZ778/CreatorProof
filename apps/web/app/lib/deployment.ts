/**
 * Upload limits shared by the browser and the Vercel route handlers.
 *
 * Vercel rejects a function request at roughly 4.5 MB before application code
 * can answer it. The 250 kB gap below leaves room for multipart boundaries and
 * the text fields that accompany the image. Keeping the image itself at 4 MB
 * also bounds the amount of image data the small Render service must decode.
 */
export const MAX_IMAGE_UPLOAD_BYTES = 4_000_000;
export const MAX_PROXY_REQUEST_BYTES = 4_250_000;
export const MAX_IMAGE_PIXELS = 6_000_000;
export const MAX_JSON_REQUEST_BYTES = 64_000;

export const ALLOWED_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
]);

export function formatBytes(bytes: number): string {
  return `${(bytes / 1_000_000).toFixed(bytes % 1_000_000 === 0 ? 0 : 1)} MB`;
}

export function validateImageMetadata(file: Pick<File, "size" | "type">): string | null {
  if (file.size <= 0) return "Choose a non-empty image file.";
  if (file.size > MAX_IMAGE_UPLOAD_BYTES) {
    return `Images must be ${formatBytes(MAX_IMAGE_UPLOAD_BYTES)} or smaller.`;
  }
  if (!ALLOWED_IMAGE_TYPES.has(file.type.toLowerCase())) {
    return "Use a PNG, JPEG, or WebP image.";
  }
  return null;
}
