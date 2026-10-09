/** A finite gateway contract: never a general-purpose authenticated proxy. */
export function phase1Route(parts: string[], method: string): string | null {
  if (parts.some((p) => !/^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)?$/.test(p))) return null;
  const path = parts.join("/");
  const id = "[A-Za-z0-9_-]+";
  const get = new RegExp(`^(?:works/${id}/(?:rights-policy(?:/[1-9][0-9]{0,5})?|ai-preferences|ai\\.txt|tdm-policy|rights-statement|contributions(?:/verify)?|provenance)|scans/${id}/(?:provenance|evidence-matrix)|investigations/${id})$`);
  const post = new RegExp(`^(?:works/${id}/(?:rights-policy|contributions|verification-token|provenance/inspect)|scans/${id}/(?:verification-token|provenance/inspect|evidence-matrix/corrections)|investigations/(?:scans/${id}|${id}/decision))$`);
  const allowed = method === "GET" ? get.test(path) : method === "POST" ? post.test(path) : method === "DELETE" && new RegExp(`^verification-tokens/${id}$`).test(path);
  return allowed ? `/v1/${path}` : null;
}
export const USE_CONTEXT_KEYS = ["territory", "channel", "audience", "transformation", "platform", "model", "rights_permission"] as const;
export function useContextFromForm(form: FormData): Record<string, string> {
  return Object.fromEntries(USE_CONTEXT_KEYS.map((key) => [key, String(form.get(`use_${key}`) || "").trim()]).filter(([, value]) => value));
}
export function completionFields(fields: Record<string, string | string[]>): Record<string, unknown> {
  if (typeof fields.use_context !== "string") return fields;
  const context: unknown = JSON.parse(fields.use_context);
  if (!context || typeof context !== "object" || Array.isArray(context)) throw new Error("Intended-use context must be an object.");
  return { ...fields, use_context: context };
}
export function validPublicToken(token: string): boolean { return /^[A-Za-z0-9_-]{64}$/.test(token); }
export function isPublicVerificationApiPath(path: string): boolean { return /^\/api\/public-verification\/[A-Za-z0-9_-]{64}$/.test(path); }
