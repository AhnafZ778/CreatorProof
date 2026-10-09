export type Json = Record<string, unknown>;
export type Permission = "ALLOW" | "DENY" | "LICENSE_REQUIRED" | "REVIEW" | "UNKNOWN" | "NOT_APPLICABLE";
export const PERMISSIONS: { key: string; label: string; group: string; description: string }[] = [
  { key: "search_indexing_permission", label: "Search indexing", group: "Discovery", description: "Include this work in search indexes." },
  { key: "commercial_search_permission", label: "Commercial search", group: "Discovery", description: "Use the work in commercial search services." },
  { key: "AI_training_permission", label: "General AI training", group: "Training", description: "Use this work as AI training material." },
  { key: "noncommercial_training_permission", label: "Noncommercial training", group: "Training", description: "Train models for noncommercial purposes." },
  { key: "commercial_training_permission", label: "Commercial training", group: "Training", description: "Train models used commercially." },
  { key: "fine_tuning_permission", label: "Model fine-tuning", group: "Training", description: "Adapt an existing model using this work." },
  { key: "style_reference_permission", label: "Style reference", group: "Creation", description: "Use the work as a reference for style." },
  { key: "image_to_image_permission", label: "Image-to-image", group: "Creation", description: "Generate a new image from this work." },
  { key: "image_editing_permission", label: "AI image editing", group: "Creation", description: "Make AI-assisted changes to this work." },
  { key: "derivative_generation_permission", label: "Generated derivatives", group: "Creation", description: "Create derived works through generation." },
  { key: "likeness_use_permission", label: "Likeness use", group: "Identity", description: "Use a depicted person's likeness." },
];
export const PERMISSION_OPTIONS: [Permission, string][] = [["UNKNOWN", "Not specified"], ["ALLOW", "Allowed"], ["DENY", "Not allowed"], ["LICENSE_REQUIRED", "License required"], ["REVIEW", "Ask for review"], ["NOT_APPLICABLE", "Not applicable"]];
export function record(value: unknown): Json { return value && typeof value === "object" && !Array.isArray(value) ? value as Json : {}; }
export function rows(value: unknown): Json[] { return Array.isArray(value) ? value.map(record) : []; }
export function str(value: unknown, fallback = ""): string { return typeof value === "string" ? value : fallback; }
export function labels(value: unknown): string[] { return Array.isArray(value) ? value.filter((x): x is string => typeof x === "string") : []; }
export function readable(value: unknown): string { return str(value, "Unknown").replaceAll("_", " ").toLowerCase().replace(/^./, (s) => s.toUpperCase()); }
function utcDate(value: unknown): Date { const text = str(value); return new Date(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(text) ? `${text}Z` : text); }
export function dateLabel(value: unknown): string { const date = utcDate(value); return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString(); }
export function toLocalDate(value: unknown): string { const date = utcDate(value); return Number.isNaN(date.getTime()) ? "" : new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); }
export function csv(value: string): string[] { return [...new Set(value.split(",").map((v) => v.trim()).filter(Boolean))]; }
export function errorMessage(body: unknown, fallback = "The request could not be completed."): string {
  const detail = record(body).detail;
  if (typeof detail === "string") return detail;
  if (typeof record(detail).message === "string") return String(record(detail).message);
  if (Array.isArray(detail)) return detail.map((v) => { const field = labels(record(v).loc).filter((s) => s !== "body").join(" / "); return `${field ? `${field}: ` : ""}${str(record(v).msg, "Check this field")}`; }).join(". ");
  return fallback;
}
export class ApiError extends Error { constructor(message: string, public status: number, public body: Json = {}) { super(message); } }
export async function api<T = Json>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/phase1/${path}`, { ...options, cache: "no-store", headers: { ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers }, signal: options.signal ?? AbortSignal.timeout(120000) });
  const body: unknown = response.status === 204 ? {} : await response.json();
  if (!response.ok) throw new ApiError(errorMessage(body), response.status, record(body));
  return body as T;
}
export function downloadJson(value: unknown, name: string) { downloadText(JSON.stringify(value, null, 2), name, "application/json"); }
export function downloadText(value: string, name: string, type = "text/plain") {
  const url = URL.createObjectURL(new Blob([value], { type }));
  const a = document.createElement("a"); a.href = url; a.download = name; document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
