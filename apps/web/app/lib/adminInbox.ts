export type AdminRecord = Record<string, any>;
export type InboxItem = {
  key: string;
  scanId: string;
  detection?: AdminRecord;
  asset?: AdminRecord;
  reviewCase?: AdminRecord;
  source: string;
  title: string;
  classification: string;
  createdAt: string;
};

export function adminInbox(detections: AdminRecord[], cases: AdminRecord[], assets: AdminRecord[]): InboxItem[] {
  const items = new Map<string, InboxItem>();
  for (const detection of detections) {
    const scanId = String(detection.scan_id || "");
    if (!scanId) continue;
    items.set(scanId, {
      key: scanId, scanId, detection, reviewCase: detection.review_case || undefined,
      source: String(detection.source_provider || "User upload"),
      title: String(detection.stored_case?.case_title || detection.source_metadata?.title || detection.matched_work?.title || "Submitted image"),
      classification: String(detection.classification || "REVIEW"),
      createdAt: String(detection.created_at || ""),
    });
  }
  for (const asset of assets) {
    const scanId = String(asset.scan_id || "");
    if (!scanId) continue;
    const existing = items.get(scanId);
    if (existing) {
      existing.asset = asset;
      existing.source = String(asset.provider || existing.source);
      existing.title = String(asset.title || existing.title);
    } else if (["COPIED", "AI_GENERATED_VERSION", "AI_SIGNAL_ONLY"].includes(String(asset.classification))) {
      items.set(scanId, {
        key: scanId, scanId, asset, source: String(asset.provider),
        title: String(asset.title || "Observed image"), classification: String(asset.classification),
        createdAt: String(asset.first_seen_at || ""),
      });
    }
  }
  for (const reviewCase of cases) {
    const scanId = String(reviewCase.scan_id || "");
    if (!scanId) continue;
    const existing = items.get(scanId);
    if (existing) existing.reviewCase = reviewCase;
    else items.set(scanId, {
      key: scanId, scanId, reviewCase, source: "User scan", title: "Submitted image",
      classification: "REVIEW", createdAt: String(reviewCase.created_at || ""),
    });
  }
  return [...items.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

export function needsAdminReview(item: InboxItem): boolean {
  return !["RESOLVED", "CLOSED"].includes(String(item.reviewCase?.state || "OPEN"));
}

export function flagLabel(item: InboxItem): string {
  if (item.detection?.category === "ASSESSMENT_GAP" || item.detection?.flag_category === "ASSESSMENT_GAP") return "Assessment incomplete";
  const reasons: string[] = Array.isArray(item.detection?.flag_reasons) ? item.detection.flag_reasons : [];
  if (item.detection?.stored_case?.comparison_kind === "AI_EDIT" && item.detection?.match_status === "MATCH_FOUND") return "Artwork match · documented AI edit";
  if (reasons.includes("AI_ORIGIN_INDICATORS")) return reasons.includes("CATALOG_MATCH") ? "Artwork match with AI indicators" : "AI-generation indicators";
  if (reasons.includes("CREATOR_RESEMBLANCE")) return "Creator resemblance";
  if (reasons.includes("COPY_EVIDENCE_INCONCLUSIVE")) return "Copy evidence needs review";
  const classification = item.classification;
  if (classification === "AI_GENERATED_VERSION") return "Artwork match with AI indicators";
  if (classification === "COPIED") return "Registered artwork match";
  if (/AI_|SYNTHETIC/.test(classification)) return "AI-generation indicators";
  if (/STYLE|RESEMBLANCE/.test(classification)) return "Creator resemblance";
  return "Policy review needed";
}

export function mediaProxyPath(value: unknown): string {
  return typeof value === "string" && (/^\/v1\/(?:scans|works)\/[A-Za-z0-9_-]+\/media$/.test(value) || /^\/v1\/admin\/stored-cases\/scn_[a-f0-9]{32}\/media\/(?:candidate|reference)$/.test(value)) ? `/api/${value.slice(4)}` : "";
}
