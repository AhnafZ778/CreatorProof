type RecordValue = Record<string, unknown>;
function record(value: unknown): RecordValue {
  return value && typeof value === "object" && !Array.isArray(value) ? value as RecordValue : {};
}
function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

export type SavedAdminReview = {
  scanId: string;
  category: "CONTENT_FLAG" | "ASSESSMENT_GAP";
  reasons: string[];
  countryCode: string | null;
  sourceUrl: string | null;
  sourceKind: string | null;
  intendedUse: string | null;
  matchedWorkId: string | null;
  useContext: Record<string, string>;
};

/** Display receipt only when the server confirms a completed, persisted inbox item. */
export function savedAdminReview(scan: RecordValue): SavedAdminReview | null {
  const review = record(scan.admin_review);
  const scanId = text(scan.id);
  if (scan.state !== "COMPLETED" || review.saved !== true || review.status !== "needs_review" || !scanId) return null;
  if (review.category !== "CONTENT_FLAG" && review.category !== "ASSESSMENT_GAP") return null;
  const submission = record(scan.submission_context);
  const country = text(submission.country_code);
  const source = text(submission.source_url);
  let sourceUrl: string | null = null;
  if (source) {
    try {
      const url = new URL(source);
      if (["http:", "https:"].includes(url.protocol) && !url.username && !url.password) sourceUrl = url.toString();
    } catch { /* A malformed optional link is never rendered as a navigation target. */ }
  }
  return {
    scanId,
    category: review.category,
    reasons: Array.isArray(review.reasons) ? [...new Set(review.reasons.filter((reason): reason is string => typeof reason === "string" && reason.trim().length > 0))] : [],
    countryCode: country && /^[A-Z]{2}$/.test(country) ? country : null,
    sourceUrl,
    sourceKind: text(submission.source_kind),
    intendedUse: text(scan.intended_use),
    matchedWorkId: scan.match_status === "MATCH_FOUND" ? text(scan.top_match_work_id) : null,
    useContext: Object.fromEntries(Object.entries(record(submission.use_context)).filter((entry): entry is [string, string] => typeof entry[1] === "string" && entry[1].trim().length > 0)),
  };
}

export function adminReviewHref(scanId: string): string {
  return `/admin?scan_id=${encodeURIComponent(scanId)}#admin-review-inbox`;
}
