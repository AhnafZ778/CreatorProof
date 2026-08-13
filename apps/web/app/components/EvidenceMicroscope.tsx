"use client";

import { useState } from "react";

export type LocalImagePreview = {
  url: string;
  name: string;
};

type Point = [number, number];

type Correspondence = {
  id: string;
  query: Point;
  reference: Point;
  descriptor_distance: number;
  transfer_error_px?: number;
  region_id?: string | null;
  evidence_type: string;
};

type Region = {
  id: string;
  kind: string;
  label: string;
  query_polygon: Point[];
  reference_polygon: Point[];
  supporting_inliers: number;
  support_fraction?: number;
  query_coverage: number;
  reference_coverage?: number;
  reprojection_error_px: number | null;
};

type Visualization = {
  query_size: [number, number];
  reference_size: [number, number];
  correspondences: Correspondence[];
  regions: Region[];
  display_notes: string[];
};

type GeometryMetrics = {
  inliers?: number;
  tentative_matches?: number;
  inlier_ratio?: number;
  query_coverage?: number;
  reference_coverage?: number;
  reprojection_error?: number | null;
  symmetric_reprojection_error?: number | null;
  validated?: boolean;
  rejection_reasons?: string[];
};

type AlignedPerceptual = {
  available: boolean;
  overlap_ratio: number;
  luminance_correlation?: number | null;
  gradient_correlation?: number | null;
  gradient_magnitude_similarity?: number | null;
  structural_similarity?: number | null;
  color_similarity?: number | null;
  structure_consensus?: number | null;
  reason?: string | null;
};

type FusionEvidence = {
  evidence_index: number;
  evidence_tier: "VERY_HIGH" | "HIGH" | "REVIEW" | "LOW" | string;
  classification: string;
  match_supported: boolean;
  review_supported: boolean;
  geometry_quality: number;
  independent_support_count: number;
  signal_states: Record<string, string>;
  reason_codes: string[];
  score_semantics: string;
};

type CandidateEvidence = {
  work_id: string;
  title: string;
  exact_sha256: boolean;
  phash_distance: number;
  phash_similarity: number;
  retrieval_rank?: number;
  verification_rank?: number;
  retrieval_provider?: string;
  retrieval_score?: number;
  ai_similarity?: number | null;
  verification_state?: string;
  geometry: GeometryMetrics;
  aligned_perceptual?: AlignedPerceptual;
  fusion?: FusionEvidence;
  visualization: Visualization;
  copy_evidence_score?: number;
  prototype_evidence_score?: number;
};

type PaletteColor = { hex: string; share: number };

type StyleFactors = {
  palette: number;
  tone: number;
  stroke_orientation: number;
  texture: number;
  diagnostic_similarity: number;
};

type StyleCell = {
  id: string;
  row: number;
  column: number;
  score: number;
  best_partner: { row: number; column: number };
  factors: StyleFactors;
};

type StyleDiagnostics = {
  query_size: [number, number];
  reference_size: [number, number];
  factors: StyleFactors;
  query_palette: PaletteColor[];
  reference_palette: PaletteColor[];
  tile_map: {
    grid_size: number;
    query_cells: StyleCell[];
    reference_cells: StyleCell[];
    semantics: string;
  };
};

type StyleProfile = {
  profile_id: string;
  creator: string;
  sample_count: number;
  profile_strength: string;
  prototype_similarity: number;
  robust_member_similarity?: number;
  profile_similarity?: number;
  raw_pool_similarity?: number;
  csls_score?: number | null;
  readout_score?: number;
  readout_method?: string;
  readout_rank?: number;
  catalog_percentile?: number;
  raw_cosine_interpretable?: boolean | null;
  discrimination_gap?: number | null;
  worst_cross_creator?: string | null;
  content_similarity?: number | null;
  style_content_gap?: number | null;
  within_profile_cohesion?: number | null;
  catalog_relative_z?: number | null;
  exemplar_work_id: string;
  exemplar_title: string;
  exemplar_similarity: number;
};

type StyleDecision = {
  evidence_index: number;
  evidence_tier: string;
  classification: string;
  review_recommended: boolean;
  independent_support_count?: number;
  learned_style_similarity?: number | null;
  mechanics_similarity?: number | null;
  tile_consistency?: number | null;
  content_similarity?: number | null;
  style_content_gap?: number | null;
  content_confound_state?: string;
  profile_reliability?: string;
  reason_codes?: string[];
  score_semantics?: string;
  calibration_state?: string;
  negative_tail_p?: number | null;
  positive_support_percentile?: number | null;
  false_match_control_supported?: boolean;
};

type StyleAnalysis = {
  customer_facing_lane?: string;
  provider: string;
  learned_provider_active: boolean;
  fallback_reason?: string | null;
  calibration_state: string;
  score_semantics?: string;
  top_vs_runner_up_margin?: number | null;
  readout?: {
    method?: string;
    csls_active?: boolean;
    csls_k_requested?: number;
    reference_count?: number;
    profile_count?: number;
    content_control_active?: boolean;
    content_control_reason?: string | null;
  };
  top_profiles: StyleProfile[];
  diagnostics: StyleDiagnostics | null;
  decision?: StyleDecision | null;
  limitations?: string[];
};

type SyntheticMember = {
  provider: string;
  model_version?: string | null;
  source_scope?: string;
  evidence_family?: string;
  score_semantics?: string;
  calibrated: boolean;
  calibration_state?: string;
  aggregate_score: number;
  global_delivery_score?: number;
  spatial_consensus_score?: number | null;
  spatial_support_count?: number;
  spatial_corroborated?: boolean;
  view_standard_deviation: number;
  transform_stability: number;
  warnings?: string[];
};

type SyntheticPresentationFact = {
  label: string;
  value: string;
  detail: string;
};

type SyntheticPresentation = {
  state: string;
  tone: string;
  headline: string;
  summary: string;
  action: string;
  show_domain_score?: boolean;
  domain_score?: number | null;
  domain_score_label?: string;
  facts?: SyntheticPresentationFact[];
};

type OriginScoreFactor = {
  id: string;
  label: string;
  signal_score?: number | null;
  quality_score?: number | null;
  status: string;
  detail: string;
};

type OriginScorecard = {
  signal_score: number;
  signal_label: string;
  evidence_quality_score: number;
  evidence_quality_label: string;
  score_semantics: string;
  plain_explanation: string;
  factors: OriginScoreFactor[];
};

type VisibleMarker = {
  kind?: string;
  matched_phrase?: string;
  recognized_text?: string;
  ocr_confidence?: number;
  normalized_box?: [number, number, number, number];
};

type VisibleMarkerSignal = {
  available?: boolean;
  checked?: boolean;
  classification?: string;
  supports_ai_origin_review?: boolean;
  marker_strength?: number | null;
  markers?: VisibleMarker[];
};

type SyntheticOrigin = {
  policy_mode?: "DISABLED" | "INFORMATIONAL" | "REQUIRED" | string;
  execution_state?: string;
  classification: string;
  evidence_tier: string;
  review_recommended: boolean;
  fused_detector_score?: number | null;
  score_semantics?: string;
  detector_count?: number;
  evidence_family_count?: number;
  calibrated_family_count?: number;
  positive_family_count?: number;
  negative_clearance_supported?: boolean;
  detector_disagreement?: number | null;
  transform_stability?: number | null;
  provenance_signal?: {
    status?: string;
    provider?: string;
    ai_assertion_present?: boolean;
    trusted_ai_assertion?: boolean;
  };
  visible_marker_signal?: VisibleMarkerSignal;
  scorecard?: OriginScorecard;
  members?: SyntheticMember[];
  presentation?: SyntheticPresentation;
  forensic_diagnostics?: Record<string, number | string>;
  reason_codes?: string[];
  limitations?: string[];
};

type ProofData = {
  anchor_status?: string;
  provider?: string;
  packet_hash_sha256?: string;
  commitment_scope?: string;
  receipt?: Record<string, unknown> | null;
};

type JointRisk = {
  classification?: string;
  headline?: string;
  ai_origin_supported?: boolean;
  ai_origin_review?: boolean;
  style_supported?: boolean;
  copy_supported?: boolean;
  case_action?: string;
  recommended_action?: string;
  coverage_status?: string;
  origin_policy_mode?: string;
  semantics?: string;
};

type EvidenceScope = {
  snapshot_id?: string;
  snapshot_digest_sha256?: string;
  created_at?: string;
  tenant_id?: string;
  catalog_id?: string;
  catalog_version?: string;
  coverage_status?: "COMPLETE" | "EMPTY_SCOPE" | "PARTIAL" | "DEGRADED" | "TRUNCATED" | "FAILED" | string;
  coverage_reason_codes?: string[];
  complete_for_declared_catalog?: boolean;
  eligible_reference_count?: number;
  nominated_candidate_count?: number;
  verified_candidate_count?: number;
  omitted_candidate_count?: number;
  failed_candidate_count?: number;
  candidate_limit?: number;
  retrieval_requirement?: string;
  descriptor_coverage?: {
    provider?: string;
    available_reference_count?: number;
    missing_reference_count?: number;
  };
  query_counts?: {
    whole_image?: number;
    regional?: number;
  };
  provider_identity?: {
    requested_retrieval_provider?: string;
    executed_retrieval_provider?: string;
    model?: string;
    preprocessing?: string;
  };
  omitted_reference_reasons?: Array<{ work_id?: string; reason_code?: string }>;
};

type EvidencePacket = {
  scope?: EvidenceScope;
  model_bundle?: Record<string, unknown>;
  matches?: CandidateEvidence[];
  style_analysis?: StyleAnalysis;
  synthetic_origin?: SyntheticOrigin;
  provenance?: {
    provider?: string;
    status?: string;
    reason_codes?: string[];
    manifest_summary?: Record<string, unknown> | null;
  };
  decision?: {
    match_status?: string;
    policy_action?: string;
    joint_risk?: JointRisk;
  };
  proof?: ProofData;
  limitations?: string[];
};

type ViewMode = "overview" | "origin" | "copy" | "structure" | "style" | "stylemap";
type ImageRect = { x: number; y: number; width: number; height: number };

type ModeMeta = {
  number: string;
  label: string;
  lane: string;
  short: string;
  guidance: string;
};

const VIEWBOX_WIDTH = 1500;
const VIEWBOX_HEIGHT = 610;
const QUERY_BOX = { x: 30, y: 98, width: 610, height: 450 };
const REFERENCE_BOX = { x: 860, y: 98, width: 610, height: 450 };
const REGION_COLORS = ["#91b99c", "#d2a45f", "#8da4c0", "#bb8d8d"];
const MODE_META: Record<ViewMode, ModeMeta> = {
  overview: {
    number: "01",
    label: "Simple summary",
    lane: "START HERE",
    short: "The result and next step",
    guidance: "Read the result first. Open another view only when you want to understand one question in more detail.",
  },
  origin: {
    number: "02",
    label: "Was AI used?",
    lane: "AI CHECK",
    short: "Score, visible labels, and source info",
    guidance: "Read the AI signal and evidence quality together. A low-quality score never clears an image as human-made.",
  },
  copy: {
    number: "03",
    label: "Does it reuse a work?",
    lane: "WORK MATCH",
    short: "Closest stored work and matched areas",
    guidance: "Use this to see whether the candidate reuses the same composition, crop, objects, or layout as a stored work.",
  },
  structure: {
    number: "03A",
    label: "Detailed structure",
    lane: "WORK MATCH DETAIL",
    short: "Measurements after alignment",
    guidance: "This detail view explains whether the layout remains similar after colour changes, compression, blur, or retouching.",
  },
  style: {
    number: "04",
    label: "Does it resemble a creator?",
    lane: "CREATOR PROFILE",
    short: "Comparison with several creator works",
    guidance: "Use this for different content that may still resemble patterns shared across a creator's registered works.",
  },
  stylemap: {
    number: "04A",
    label: "Detailed style map",
    lane: "CREATOR PROFILE DETAIL",
    short: "Colour, tone, edge, and texture map",
    guidance: "This detail view compares visual qualities. The tiles are not copied regions and do not prove infringement.",
  },
};

const PRIMARY_MODES: ViewMode[] = ["overview", "origin", "copy", "style"];

function objectRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function packetRecord(scan: Record<string, unknown> | null): Record<string, unknown> | null {
  return objectRecord(scan?.evidence_packet);
}

export function topEvidenceWorkId(scan: Record<string, unknown> | null): string | null {
  const matches = packetRecord(scan)?.matches;
  if (!Array.isArray(matches) || matches.length === 0) return null;
  const top = objectRecord(matches[0]);
  return typeof top?.work_id === "string" ? top.work_id : null;
}

export function topStyleEvidenceWorkId(scan: Record<string, unknown> | null): string | null {
  const style = objectRecord(packetRecord(scan)?.style_analysis);
  const profiles = style?.top_profiles;
  if (!Array.isArray(profiles) || profiles.length === 0) return null;
  const top = objectRecord(profiles[0]);
  return typeof top?.exemplar_work_id === "string" ? top.exemplar_work_id : null;
}

function evidencePacket(scan: Record<string, unknown>): EvidencePacket | null {
  const packet = packetRecord(scan);
  return packet ? (packet as EvidencePacket) : null;
}

function fitImage(size: [number, number], box: typeof QUERY_BOX): ImageRect {
  const [naturalWidth, naturalHeight] = size;
  if (naturalWidth <= 0 || naturalHeight <= 0) return { ...box };
  const scale = Math.min(box.width / naturalWidth, box.height / naturalHeight);
  const width = naturalWidth * scale;
  const height = naturalHeight * scale;
  return {
    x: box.x + (box.width - width) / 2,
    y: box.y + (box.height - height) / 2,
    width,
    height,
  };
}

function mapPoint(rect: ImageRect, point: Point): Point {
  return [rect.x + point[0] * rect.width, rect.y + point[1] * rect.height];
}

function polygonPoints(rect: ImageRect, polygon: Point[]): string {
  return polygon.map((point) => mapPoint(rect, point).join(",")).join(" ");
}

function metric(value: number | null | undefined, digits = 3): string {
  return typeof value === "number" ? value.toFixed(digits) : "n/a";
}

function percent(value: number | null | undefined): string {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "n/a";
}

function tierClass(tier: string | undefined): string {
  if (tier === "VERY_HIGH" || tier === "HIGH" || tier === "PROVENANCE") return "positive";
  if (tier === "REVIEW" || tier === "INCONCLUSIVE") return "review";
  return "quiet";
}

function fallbackOriginPresentation(synthetic: SyntheticOrigin | undefined): SyntheticPresentation {
  const classification = synthetic?.classification ?? "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE";
  if (classification === "AI_PROVENANCE_CONFIRMED") {
    return {
      state: "AI_CONFIRMED",
      tone: "provenance",
      headline: "Signed provenance identifies AI use",
      summary: "Trusted Content Credentials contain an AI-use assertion.",
      action: "Review the separate copy and style results before making a rights decision.",
    };
  }
  if (classification === "LIKELY_AI_GENERATED" || classification === "AI_INDICATORS_CORROBORATED") {
    return {
      state: "AI_INDICATORS_FOUND",
      tone: "high",
      headline: "AI-generation indicators were found",
      summary: "The available origin checks recorded a strong, stable response.",
      action: "Keep this case in review and inspect copy and creator-profile evidence next.",
    };
  }
  if (classification === "AI_ORIGIN_MARKER_FOUND") {
    return {
      state: "AI_INDICATORS_NEED_REVIEW",
      tone: "review",
      headline: "A visible AI label was found",
      summary: "The image contains text that identifies AI use. The label can be copied or forged, so it is review evidence rather than proof.",
      action: "Review the highlighted label and the other evidence before using this image.",
    };
  }
  if (classification === "AI_ORIGIN_REVIEW_CANDIDATE") {
    return {
      state: "AI_INDICATORS_NEED_REVIEW",
      tone: "review",
      headline: "AI-generation indicators need review",
      summary: "At least one check responded, but the available support is not decisive.",
      action: "Do not auto-clear this image; add another independent check.",
    };
  }
  if (classification === "NO_AI_ORIGIN_EVIDENCE_DETECTED") {
    return {
      state: "NO_STRONG_AI_SIGNAL",
      tone: "low",
      headline: "No strong AI-generation indicators were found",
      summary: "This does not prove that the image was made by a human.",
      action: "Continue with copy and style checks before clearing use.",
    };
  }
  if (classification === "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE") {
    return {
      state: "CHECK_UNAVAILABLE",
      tone: "unavailable",
      headline: "AI-origin checks are not active",
      summary: "No learned origin detector produced evidence for this scan.",
      action: "Install and verify the model artifacts before relying on this lane.",
    };
  }
  if (classification === "AI_ORIGIN_CHECK_DISABLED") {
    return {
      state: "CHECK_DISABLED",
      tone: "unavailable",
      headline: "AI-origin checks were disabled by policy",
      summary: "CreatorProof deliberately made no AI-origin inference for this scan.",
      action: "Apply the recorded policy and inspect the independent work-match lane.",
    };
  }
  return {
    state: "ORIGIN_UNKNOWN",
    tone: "inconclusive",
    headline: "This scan cannot determine the image’s origin",
    summary: "The available checks were limited, unstable, low-resolution, or contradictory.",
    action: "Keep the case in review and collect another independent source of evidence.",
  };
}

function copyHeadline(copy: CandidateEvidence | undefined): string {
  if (!copy) return "No registered reference was available";
  if (copy.exact_sha256 || copy.fusion?.match_supported) return "Likely the same registered work";
  if (copy.fusion?.review_supported) return "Possible reuse needs review";
  return "No verified same-work copy was found";
}

function styleHeadline(style: StyleAnalysis | undefined): string {
  const decision = style?.decision;
  if (!decision) return "No creator profile was available";
  if (decision.evidence_tier === "VERY_HIGH" || decision.evidence_tier === "HIGH") {
    return "Strong creator-profile resemblance";
  }
  if (decision.review_recommended) return "Some creator-profile resemblance needs review";
  return "No strong creator-profile signal was found";
}

function scopePresentation(scope: EvidenceScope | undefined) {
  const status = scope?.coverage_status ?? "UNAVAILABLE";
  if (status === "COMPLETE") {
    return {
      tone: "complete",
      headline: "The declared catalog scope was completely checked",
      detail: "A source-scoped no-match is permitted only because every eligible reference passed the configured search and verification plan.",
    };
  }
  if (status === "EMPTY_SCOPE") {
    return {
      tone: "incomplete",
      headline: "This catalog contains no eligible references",
      detail: "There is nothing to compare against, so CreatorProof cannot issue a stored-work no-match or automatic clearance.",
    };
  }
  if (status === "TRUNCATED") {
    return {
      tone: "incomplete",
      headline: "Only part of the candidate set was locally verified",
      detail: "The verification budget omitted eligible references. The stored-work outcome remains scope-incomplete and requires review.",
    };
  }
  if (status === "DEGRADED") {
    return {
      tone: "incomplete",
      headline: "A required retrieval capability did not complete",
      detail: "Fallback evidence is recorded, but the configured source scope is not complete enough to support a no-match.",
    };
  }
  if (status === "PARTIAL") {
    return {
      tone: "incomplete",
      headline: "Some nominated references were not verified",
      detail: "The successful checks remain useful evidence, but incomplete verification prevents a source-scoped no-match.",
    };
  }
  if (status === "FAILED") {
    return {
      tone: "failed",
      headline: "The stored-work verification scope failed",
      detail: "No clearance inference is available. Resolve the failed checks and run the scan again.",
    };
  }
  return {
    tone: "incomplete",
    headline: "Source coverage information is unavailable",
    detail: "Treat the stored-work lane as incomplete until a typed coverage record is available.",
  };
}

function scopeCopyHeadline(scope: EvidenceScope | undefined): string {
  if (scope?.coverage_status === "EMPTY_SCOPE") return "No eligible reference exists in this catalog";
  if (scope?.coverage_status && scope.coverage_status !== "COMPLETE") {
    return "Stored-work scope is incomplete";
  }
  return "No verified same-work copy was found in the checked sources";
}

function ScopeBanner({ scope }: { scope: EvidenceScope | undefined }) {
  const presentation = scopePresentation(scope);
  const eligible = scope?.eligible_reference_count ?? 0;
  const nominated = scope?.nominated_candidate_count ?? 0;
  const verified = scope?.verified_candidate_count ?? 0;
  const omitted = scope?.omitted_candidate_count ?? 0;
  const reasons = scope?.coverage_reason_codes ?? [];
  return (
    <section className={`scopeBanner ${presentation.tone}`} aria-label="Declared source coverage" role="status">
      <div className="scopeSummary">
        <span>SOURCE COVERAGE · {scope?.coverage_status ?? "UNAVAILABLE"}</span>
        <b>{presentation.headline}</b>
        <p>{presentation.detail}</p>
      </div>
      <dl className="scopeCounts">
        <div><dt>Eligible</dt><dd>{eligible}</dd></div>
        <div><dt>Nominated</dt><dd>{nominated}</dd></div>
        <div><dt>Verified</dt><dd>{verified}</dd></div>
        <div><dt>Omitted</dt><dd>{omitted}</dd></div>
      </dl>
      <details className="scopeDetails">
        <summary>Audit the checked scope</summary>
        <div>
          <span>Catalog</span><b>{scope?.catalog_id ?? "not recorded"}</b>
          <span>Catalog version</span><code>{scope?.catalog_version ?? "not recorded"}</code>
          <span>Retrieval requirement</span><b>{scope?.retrieval_requirement ?? "not recorded"}</b>
          <span>Learned descriptors</span><b>{scope?.descriptor_coverage?.available_reference_count ?? 0}/{eligible}</b>
          <span>Coverage reasons</span><b>{reasons.length ? reasons.join(" · ") : "NONE"}</b>
          <span>Snapshot</span><code>{scope?.snapshot_id ?? "not recorded"}</code>
        </div>
      </details>
    </section>
  );
}

function indexLabel(value: number | null | undefined): string {
  return typeof value === "number" ? `${value.toFixed(2)} evidence index` : "No index available";
}

function Palette({ colors }: { colors: PaletteColor[] }) {
  return (
    <div className="paletteStrip" aria-label="Dominant palette">
      {colors.map((color) => (
        <span
          key={`${color.hex}-${color.share}`}
          style={{ background: color.hex, flexGrow: Math.max(0.08, color.share) }}
          title={`${color.hex} · ${percent(color.share)}`}
        />
      ))}
    </div>
  );
}

function FactorBars({ factors }: { factors: StyleFactors }) {
  const rows: [string, keyof StyleFactors][] = [
    ["Palette", "palette"],
    ["Tone", "tone"],
    ["Edge direction", "stroke_orientation"],
    ["Texture", "texture"],
  ];
  return (
    <div className="styleFactors">
      {rows.map(([label, key]) => (
        <div className="factorRow" key={key}>
          <div><span>{label}</span><b>{metric(factors[key], 3)}</b></div>
          <div className="factorTrack"><i style={{ width: `${Math.max(0, Math.min(1, factors[key])) * 100}%` }} /></div>
        </div>
      ))}
    </div>
  );
}

function OriginSummary({
  synthetic,
  presentation,
  provenanceStatus,
  policyMode,
}: {
  synthetic: SyntheticOrigin | undefined;
  presentation: SyntheticPresentation;
  provenanceStatus?: string;
  policyMode: string;
}) {
  const scorecard = synthetic?.scorecard;
  const signalScore = scorecard?.signal_score ?? Math.round((synthetic?.fused_detector_score ?? 0) * 100);
  const qualityScore = scorecard?.evidence_quality_score ?? 0;
  const fallbackFactors: OriginScoreFactor[] = [
    {
      id: "model_checks",
      label: "AI model checks",
      signal_score: synthetic?.fused_detector_score == null ? null : signalScore,
      quality_score: null,
      status: synthetic?.detector_count ? "Model result available" : "AI model checks unavailable",
      detail: "A model score is signal strength, not the chance that an image is AI-made.",
    },
    {
      id: "visible_label",
      label: "Visible AI label",
      signal_score: null,
      quality_score: null,
      status: "Visible-label result unavailable",
      detail: "A missing or unavailable label check is neutral.",
    },
    {
      id: "signed_source",
      label: "Signed source information",
      signal_score: null,
      quality_score: null,
      status: provenanceStatus ?? "Not checked",
      detail: "Missing signed source information does not imply human origin.",
    },
  ];
  const factors = scorecard?.factors ?? fallbackFactors;

  return (
    <div className={`originPlainPanel ${tierClass(synthetic?.evidence_tier)}`} role="status" aria-atomic="true">
      <div className="originPlainHeader">
        <span>WAS AI USED?</span>
        <em>{synthetic?.review_recommended ? "REVIEW" : "RESULT"}</em>
      </div>
      <h4>{presentation.headline}</h4>
      <p>{presentation.summary}</p>
      <div className="originScoreGrid" aria-label="AI signal and evidence quality">
        <div className="originScore signalScore">
          <span>AI signal</span>
          <b>{signalScore}<small>/100</small></b>
          <strong>{scorecard?.signal_label ?? "Signal not fully scored"}</strong>
          <p>How strongly the available checks reacted. Not an AI probability.</p>
        </div>
        <div className="originScore qualityScore">
          <span>Evidence quality</span>
          <b>{qualityScore}<small>/100</small></b>
          <strong>{scorecard?.evidence_quality_label ?? "Low"} confidence in the checks</strong>
          <p>Coverage, testing, consistency, and source trust behind this result.</p>
        </div>
        <div className="originOutcomeCard">
          <span>Plain result</span>
          <b>{presentation.headline}</b>
          <p>Read both scores together. A strong signal with weak evidence stays in review.</p>
        </div>
      </div>
      <p className="originScoreExplanation">
        {scorecard?.plain_explanation ?? "Scores explain signal strength and evidence quality separately. Neither is a probability."}
      </p>
      <div className={`originPolicyNote ${policyMode.toLowerCase()}`}>
        <b>Policy effect · {policyMode}</b>
        <span>
          {policyMode === "REQUIRED"
            ? "This lane is required and may route the recorded policy decision to review."
            : policyMode === "DISABLED"
              ? "This lane was skipped deliberately and cannot contribute an origin conclusion."
              : "This lane is recorded as context and cannot independently change pass, review, or block."}
        </span>
      </div>
      <div className="originNextStep">
        <b>What to do next</b>
        <span>{presentation.action}</span>
      </div>
      <div className="originFactorList" aria-label="Why CreatorProof reached this result">
        <h5>Why this result</h5>
        {factors.map((factor) => (
          <div key={factor.id}>
            <i className={typeof factor.signal_score === "number" ? "active" : "neutral"} aria-hidden="true" />
            <span>
              <b>{factor.label}</b>
              <strong>{factor.status}</strong>
              <small>{factor.detail}</small>
            </span>
            <em>{typeof factor.signal_score === "number" ? `${factor.signal_score}/100 signal` : "Neutral"}</em>
          </div>
        ))}
      </div>
      <details className="technicalDisclosure originTechnicalDisclosure">
        <summary>Show advanced details for judges and engineers</summary>
        <p className="technicalIntro">
          These are machine diagnostics. Raw model values are not percentages or universal
          probabilities, and a quiet result never proves human origin.
        </p>
        {presentation.show_domain_score && typeof presentation.domain_score === "number" ? (
          <div className="domainScoreReadout">
            <span>{presentation.domain_score_label ?? "CALIBRATED DOMAIN SCORE"}</span>
            <b>{metric(presentation.domain_score, 3)}</b>
          </div>
        ) : (
          <div className="domainScoreReadout withheld">
            <span>CALIBRATED MODEL SCORE NOT AVAILABLE</span>
            <b>The restored 0–100 product scores above remain explicitly non-probabilistic</b>
          </div>
        )}
        <div className="originMetricGrid">
          <div><span>ACTIVE AI MODELS</span><b>{synthetic?.detector_count ?? 0}</b><small>Individual model checks.</small></div>
          <div><span>INDEPENDENT CHECK TYPES</span><b>{synthetic?.evidence_family_count ?? 0}</b><small>Different kinds of AI evidence.</small></div>
          <div><span>RESULT CONSISTENCY</span><b>{percent(synthetic?.transform_stability)}</b><small>After JPEG, resize, and blur.</small></div>
          <div><span>MODEL DIFFERENCE</span><b>{metric(synthetic?.detector_disagreement, 3)}</b><small>Large differences force an unknown result.</small></div>
        </div>
        <div className="detectorLedger">
          <div className="detectorLedgerHead"><span>MODEL / CHECK TYPE</span><span>RAW SIGNAL</span><span>CONSISTENCY</span><span>TESTING STATE</span></div>
          {synthetic?.members?.length ? synthetic.members.map((member) => (
            <div key={`${member.provider}-${member.model_version ?? "unknown"}`}>
              <span><b>{member.provider}</b><small>{member.evidence_family ?? member.model_version ?? "family unspecified"}</small></span>
              <strong>{metric(member.aggregate_score, 3)}</strong>
              <strong>{percent(member.transform_stability)}</strong>
              <em className={member.calibrated ? "ready" : "limited"}>{member.calibration_state ?? (member.calibrated ? "CALIBRATED" : "RAW ONLY")}</em>
            </div>
          )) : <p>No AI-origin model is active. CreatorProof does not infer human origin from that absence.</p>}
        </div>
        <div className="originReasons">
          <b>Machine codes</b>
          <p>{synthetic?.reason_codes?.join(" · ") || "No origin reason codes recorded."}</p>
        </div>
      </details>
    </div>
  );
}

function OriginImageCard({
  candidate,
  markerSignal,
}: {
  candidate: LocalImagePreview | null;
  markerSignal?: VisibleMarkerSignal;
}) {
  const markers = markerSignal?.markers?.filter((item) => item.normalized_box) ?? [];
  return (
    <div className="originImageCard">
      <div><span>IMAGE BEING CHECKED</span><small>{candidate?.name ?? "uploaded image"}</small></div>
      {candidate?.url ? (
        <div className="originImagePreview">
          <img src={candidate.url} alt="Candidate submitted for AI-use analysis" />
          {markers.map((marker, index) => {
            const [left, top, right, bottom] = marker.normalized_box!;
            return (
              <span
                className="visibleMarkerBox"
                key={`${marker.recognized_text ?? marker.matched_phrase ?? "marker"}-${index}`}
                style={{
                  left: `${left * 100}%`,
                  top: `${top * 100}%`,
                  width: `${Math.max(0, right - left) * 100}%`,
                  height: `${Math.max(0, bottom - top) * 100}%`,
                }}
                title={marker.recognized_text ?? "Visible AI label"}
              ><em>AI label</em></span>
            );
          })}
        </div>
      ) : <p>Image preview unavailable.</p>}
      {markers.length ? (
        <p className="markerFoundNote"><b>Visible AI label highlighted.</b> This supports review, but visible labels can be forged or copied.</p>
      ) : (
        <p>AI-use analysis works independently from stored-work matching. No visible label is a neutral result.</p>
      )}
    </div>
  );
}

export default function EvidenceMicroscope({
  scan,
  candidate,
  copyReference,
  styleReference,
}: {
  scan: Record<string, unknown>;
  candidate: LocalImagePreview | null;
  copyReference: LocalImagePreview | null;
  styleReference: LocalImagePreview | null;
}) {
  const [mode, setMode] = useState<ViewMode>("overview");
  const [showFeaturePairs, setShowFeaturePairs] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<string | null>(null);
  const [activeStyleCell, setActiveStyleCell] = useState<string | null>(null);
  const [aiExplanation, setAiExplanation] = useState<string | null>(null);
  const [aiExplainState, setAiExplainState] = useState<"idle" | "loading" | "error">("idle");

  const packet = evidencePacket(scan);
  const copy = packet?.matches?.[0];
  const style = packet?.style_analysis;
  const synthetic = packet?.synthetic_origin;
  const proof = packet?.proof;
  const jointRisk = packet?.decision?.joint_risk;
  const scope = packet?.scope;
  const styleProfile = style?.top_profiles?.[0];
  const diagnostics = style?.diagnostics;
  const originPresentation = synthetic?.presentation ?? fallbackOriginPresentation(synthetic);
  const originPolicyMode = synthetic?.policy_mode
    ?? jointRisk?.origin_policy_mode
    ?? "INFORMATIONAL";
  const combinedHeadline = jointRisk?.headline ?? originPresentation.headline;
  const combinedAction = jointRisk?.recommended_action ?? originPresentation.action;
  const needsReview = jointRisk?.case_action?.startsWith("REVIEW")
    || jointRisk?.case_action === "ACTIVATE_AI_CHECKS";
  if (!copy?.visualization) {
    return (
      <section id="analysis" className="microscope mode-origin originOnlyCase" aria-labelledby="origin-only-title">
        <div className="plainCaseHeader">
          <div className="eyebrow">EVIDENCE CASE / v0.9.2 / TRUTHFUL SCOPE</div>
          <h2 id="origin-only-title">Here is what CreatorProof can establish from this scan.</h2>
          <p>Origin, same-work copying, and creator-profile resemblance are separate checks.</p>
        </div>
        <ScopeBanner scope={scope} />
        <div className={`bottomLineBanner ${needsReview ? "review" : "quiet"}`} role="status" aria-atomic="true">
          <span>THE BOTTOM LINE</span>
          <strong>{combinedHeadline}</strong>
          <p>{combinedAction}</p>
          <b>The work-match outcome cannot clear use unless source coverage is complete.</b>
        </div>
        <div className="plainLaneGrid" aria-label="Three evidence lanes">
          <div className={`plainLaneCard origin ${tierClass(synthetic?.evidence_tier)}`}>
            <span>WAS AI USED?</span><b>{originPresentation.headline}</b><small>AI signal {synthetic?.scorecard?.signal_score ?? 0}/100 · not a probability</small>
          </div>
          <div className="plainLaneCard copy quiet">
            <span>SAME-WORK COPY</span><b>{scopeCopyHeadline(scope)}</b><small>Open the source-coverage record above before relying on this lane.</small>
          </div>
          <div className="plainLaneCard style quiet">
            <span>CREATOR PROFILE</span><b>No creator profile was available</b><small>A useful profile needs multiple registered works.</small>
          </div>
        </div>
        <div className="originWorkbench originOnlyWorkbench">
          <OriginImageCard candidate={candidate} markerSignal={synthetic?.visible_marker_signal} />
          <OriginSummary
            synthetic={synthetic}
            presentation={originPresentation}
            provenanceStatus={packet?.provenance?.status}
            policyMode={originPolicyMode}
          />
        </div>
      </section>
    );
  }

  const fusion = copy.fusion;
  const aligned = copy.aligned_perceptual;
  const styleMode = mode === "style" || mode === "stylemap";
  const reference = styleMode ? styleReference : copyReference;
  const querySize = styleMode && diagnostics ? diagnostics.query_size : copy.visualization.query_size;
  const referenceSize = styleMode && diagnostics ? diagnostics.reference_size : copy.visualization.reference_size;
  const queryRect = fitImage(querySize, QUERY_BOX);
  const referenceRect = fitImage(referenceSize, REFERENCE_BOX);
  const geometryValidated = Boolean(copy.geometry.validated || copy.exact_sha256);
  const canShowImages = Boolean(candidate?.url && (mode === "origin" || reference?.url));
  const activeCorrespondence = copy.visualization.correspondences.find((item) => item.id === activeEvidence);
  const activeRegion = copy.visualization.regions.find((item) => item.id === activeEvidence);
  const allStyleCells = diagnostics ? [...diagnostics.tile_map.query_cells, ...diagnostics.tile_map.reference_cells] : [];
  const selectedStyleCell = allStyleCells.find((item) => item.id === activeStyleCell) ?? null;
  const evidenceIndex = copy.copy_evidence_score ?? fusion?.evidence_index ?? copy.prototype_evidence_score;
  const styleDecision = style?.decision;
  const styleEvidenceIndex = styleDecision?.evidence_index;
  const rawStyleScore = styleProfile?.raw_pool_similarity ?? styleProfile?.profile_similarity ?? styleProfile?.prototype_similarity;
  const activeMode = MODE_META[mode];
  const receipt = proof?.receipt;
  const explorerUrl = typeof receipt?.explorer_url === "string" ? receipt.explorer_url : null;
  const proofScope = typeof receipt?.anchor_scope === "string" ? receipt.anchor_scope : "NOT_ANCHORED";

  async function explainEvidence() {
    setAiExplainState("loading");
    setAiExplanation(null);
    try {
      const response = await fetch("/api/ai/explain", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          evidence: {
            source_scope: scope ?? null,
            copy_lane: {
              title: copy!.title,
              verification_state: copy!.verification_state,
              fusion: copy!.fusion,
              ai_similarity: copy!.ai_similarity,
              geometry: copy!.geometry,
              aligned_perceptual: copy!.aligned_perceptual,
            },
            style_lane: style ? {
              provider: style.provider,
              learned_provider_active: style.learned_provider_active,
              calibration_state: style.calibration_state,
              top_profile: styleProfile,
              decision: styleDecision,
              readout: style.readout,
              diagnostics: diagnostics?.factors,
            } : null,
            ai_origin_lane: synthetic ?? null,
            provenance: packet?.provenance ?? null,
            joint_risk: jointRisk ?? null,
            proof: proof ? {
              anchor_status: proof.anchor_status,
              provider: proof.provider,
              commitment_scope: proof.commitment_scope,
            } : null,
          },
        }),
      });
      const body = (await response.json()) as { explanation?: unknown; error?: unknown };
      if (!response.ok || typeof body.explanation !== "string") {
        throw new Error(typeof body.error === "string" ? body.error : "OpenRouter explainer unavailable");
      }
      setAiExplanation(body.explanation);
      setAiExplainState("idle");
    } catch (error) {
      setAiExplanation(error instanceof Error ? error.message : "OpenRouter explainer unavailable");
      setAiExplainState("error");
    }
  }

  function tileRect(cell: StyleCell, rect: ImageRect, gridSize: number) {
    return {
      x: rect.x + (cell.column * rect.width) / gridSize,
      y: rect.y + (cell.row * rect.height) / gridSize,
      width: rect.width / gridSize,
      height: rect.height / gridSize,
    };
  }

  return (
    <section id="analysis" className={`microscope mode-${mode}`} aria-labelledby="microscope-title">
      <div className="plainCaseHeader">
        <div className="eyebrow">EVIDENCE CASE / v0.9.2 / TRUTHFUL SCOPE</div>
        <h2 id="microscope-title">Understand this case in one glance.</h2>
        <p>AI origin, same-work copying, and creator-profile resemblance are separate questions. Open a lane only when you need its supporting evidence.</p>
      </div>

      <ScopeBanner scope={scope} />

      <div className={`bottomLineBanner ${needsReview ? "review" : "quiet"}`} role="status" aria-atomic="true">
        <span>THE BOTTOM LINE</span>
        <strong>{combinedHeadline}</strong>
        <p>{combinedAction}</p>
        <div className="jointSignalPills" aria-label="Signals supporting this summary">
          <span className={jointRisk?.ai_origin_supported || jointRisk?.ai_origin_review ? "on" : "off"}>AI check</span>
          <span className={jointRisk?.copy_supported ? "on" : "off"}>Stored-work match</span>
          <span className={jointRisk?.style_supported ? "on" : "off"}>Creator profile</span>
        </div>
      </div>

      <div className="plainLaneGrid" aria-label="Three evidence lanes">
        <button type="button" className={`plainLaneCard origin ${tierClass(synthetic?.evidence_tier)}`} onClick={() => setMode("origin")}>
          <span>01 · WAS AI USED?</span><b>{originPresentation.headline}</b><small>AI signal {synthetic?.scorecard?.signal_score ?? 0}/100 · evidence quality {synthetic?.scorecard?.evidence_quality_score ?? 0}/100</small><em>See why →</em>
        </button>
        <button type="button" className={`plainLaneCard copy ${tierClass(fusion?.evidence_tier)}`} onClick={() => setMode("copy")}>
          <span>02 · STORED-WORK MATCH</span><b>{copyHeadline(copy)}</b><small>{indexLabel(evidenceIndex)} · not a probability</small><em>See matched areas →</em>
        </button>
        <button type="button" className={`plainLaneCard style ${tierClass(styleDecision?.evidence_tier)}`} onClick={() => setMode("style")} disabled={!styleProfile}>
          <span>03 · CREATOR PROFILE</span><b>{styleHeadline(style)}</b><small>{indexLabel(styleEvidenceIndex)} · not a legal conclusion</small><em>{styleProfile ? "See creator comparison →" : "Register multiple works first"}</em>
        </button>
      </div>

      <details className="technicalDisclosure signalDisclosure">
        <summary>Show advanced system details</summary>
        <div className="signalMatrix" aria-label="Technical evidence signals">
          <div className="signalCard originSignal"><i /><span>Independent AI checks</span><b>{synthetic?.evidence_family_count ?? 0} types</b><small>{synthetic?.classification ?? "unavailable"}</small></div>
          <div className="signalCard retrievalSignal"><i /><span>SSCD retrieval</span><b>{metric(copy.ai_similarity, 3)}</b><small>{fusion?.signal_states?.retrieval ?? "retrieval signal"}</small></div>
          <div className="signalCard geometrySignal"><i /><span>Local geometry</span><b>{geometryValidated ? metric(fusion?.geometry_quality, 3) : "rejected"}</b><small>{copy.geometry.inliers ?? 0}/{copy.geometry.tentative_matches ?? 0} verified inliers</small></div>
          <div className="signalCard structureSignal"><i /><span>Aligned structure</span><b>{metric(aligned?.structure_consensus, 3)}</b><small>{fusion?.signal_states?.aligned_structure ?? aligned?.reason ?? "not measured"}</small></div>
          <div className="signalCard styleSignal"><i /><span>Style evidence</span><b>{metric(styleEvidenceIndex, 3)}</b><small>{styleDecision?.evidence_tier ?? "unavailable"} · {styleProfile?.creator ?? "no profile"}</small></div>
          <div className="signalCard proofSignal"><i /><span>Evidence receipt</span><b>{proof?.anchor_status ?? "NONE"}</b><small>{proofScope === "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY" ? "public EAS transaction" : "local transparency receipt"}</small></div>
        </div>
      </details>

      <div className="analysisWorkbench">
        <aside className="analysisSidebar" aria-label="Analysis navigation">
          <div className="analysisSidebarHeading">
            <small>4 SIMPLE VIEWS</small>
            <strong>What do you want to know?</strong>
            <p>Start with the summary. Detailed measurements stay inside their related view.</p>
          </div>
          <div className="modeRail" role="group" aria-label="Evidence visualization mode">
            {PRIMARY_MODES.map((item) => {
              const meta = MODE_META[item];
              const disabled = (item === "style" || item === "stylemap") && !styleProfile;
              return (
                <button
                  key={item}
                  type="button"
                  className={`modeButton modeButton-${item} ${mode === item ? "active" : ""}`}
                  disabled={disabled}
                  aria-pressed={mode === item}
                  onClick={() => {
                    setMode(item);
                    setActiveEvidence(null);
                    setActiveStyleCell(null);
                  }}
                >
                  <span className="modeNumber">{meta.number}</span>
                  <span className="modeCopy"><small>{meta.lane}</small><b>{meta.label}</b><em>{disabled ? "Needs a creator profile" : meta.short}</em></span>
                  <span className="modeArrow" aria-hidden="true">→</span>
                </button>
              );
            })}
          </div>
          <div className="laneKey">
            <div><i className="originDot" /><span><b>AI check</b> Was AI likely involved?</span></div>
            <div><i className="copyDot" /><span><b>Work match</b> Is the same work reused?</span></div>
            <div><i className="styleDot" /><span><b>Creator profile</b> Does a different image resemble the creator?</span></div>
          </div>
        </aside>

        <div className="analysisStage">
          <div className="activeModeBanner">
            <span className="activeModeNumber">{activeMode.number}</span>
            <div>
              <small>{activeMode.lane} / ACTIVE VIEW</small>
              <h3>{activeMode.label}</h3>
              <p>{activeMode.guidance}</p>
            </div>
            <div className="modeAction">
              {mode === "copy" ? (
                <div className="modeActionButtons">
                  <button type="button" className={showFeaturePairs ? "active" : ""} disabled={!geometryValidated} onClick={() => setShowFeaturePairs((current) => !current)}>
                    {showFeaturePairs ? "Hide matched points" : "Show matched points"}
                  </button>
                  <button type="button" onClick={() => setMode("structure")}>Detailed structure</button>
                </div>
              ) : mode === "structure" ? (
                <button type="button" onClick={() => setMode("copy")}>← Back to work match</button>
              ) : mode === "style" && diagnostics ? (
                <button type="button" onClick={() => setMode("stylemap")}>Detailed style map</button>
              ) : mode === "stylemap" && diagnostics ? (
                <div className="modeActionButtons"><button type="button" onClick={() => setMode("style")}>← Back to creator profile</button><span className="heatLegend"><i /> lower <i /> higher</span></div>
              ) : (
                <span className="modeReady"><i /> VIEW READY</span>
              )}
            </div>
          </div>

          {mode === "copy" && (
            <div className="evidenceGuide copyGuide">
              <b>How to read this:</b>
              <span>Coloured envelopes contain verified feature support. Turn on numbered pairs, then hover or click a number to inspect one measured correspondence.</span>
            </div>
          )}

          {mode === "origin" && (
            <div className="evidenceGuide originGuide">
              <b>Answer first, evidence second:</b>
              <span>Read the plain conclusion and next step. Open technical evidence only when you need model, calibration, or robustness details.</span>
            </div>
          )}

          {mode === "structure" && (
            <div className="evidenceGuide structureGuide">
              <b>How to read this:</b>
              <span>These measurements run only after robust alignment. Structure matters more than colour, so retouching cannot veto otherwise strong preserved evidence.</span>
            </div>
          )}

          {mode === "style" && (
            <div className="evidenceGuide styleGuide">
              <b>How to read this:</b>
              <span>Compare the candidate against a multi-work creator profile. Treat the result as review evidence, not a copy location or legal conclusion.</span>
            </div>
          )}

          {mode === "stylemap" && diagnostics && (
            <div className="evidenceGuide styleGuide">
              <b>How to read this:</b>
              <span>Click a tile to inspect its closest cross-image palette, tone, edge, and texture partner. Tile positions do not represent correspondence.</span>
            </div>
          )}

          {mode === "origin" && (
            <div className="originWorkbench">
              <OriginImageCard candidate={candidate} markerSignal={synthetic?.visible_marker_signal} />
              <OriginSummary
                synthetic={synthetic}
                presentation={originPresentation}
                provenanceStatus={packet?.provenance?.status}
                policyMode={originPolicyMode}
              />
            </div>
          )}

          {mode !== "origin" && (!canShowImages ? (
        <div className="microscopeEmpty">
          <b>The comparison images could not be loaded.</b>
          <span>The candidate is browser-local; registered references load through the authenticated media route.</span>
        </div>
      ) : (
        <div className="evidenceCanvasWrap">
          <svg className="evidenceCanvas" viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`} role="img" aria-label="Side-by-side CreatorProof evidence comparison">
            <text x="30" y="42" className="canvasHeading">CANDIDATE</text>
            <text x="1470" y="42" textAnchor="end" className="canvasHeading">{styleMode ? "STYLE EXEMPLAR" : "VERIFIED BEST REFERENCE"}</text>
            <text x="30" y="68" className="canvasFilename">{candidate?.name}</text>
            <text x="1470" y="68" textAnchor="end" className="canvasFilename">{reference?.name}</text>
            <text x="750" y="42" textAnchor="middle" className="canvasCenterLabel">
              {styleMode ? "STYLE / NO GEOMETRY IMPLIED" : `RETRIEVAL #${copy.retrieval_rank ?? "?"} → VERIFICATION #${copy.verification_rank ?? 1}`}
            </text>
            <rect className="imageFrame" x={queryRect.x} y={queryRect.y} width={queryRect.width} height={queryRect.height} rx="3" />
            <rect className="imageFrame" x={referenceRect.x} y={referenceRect.y} width={referenceRect.width} height={referenceRect.height} rx="3" />
            <image href={candidate?.url} x={queryRect.x} y={queryRect.y} width={queryRect.width} height={queryRect.height} preserveAspectRatio="none" />
            <image href={reference?.url} x={referenceRect.x} y={referenceRect.y} width={referenceRect.width} height={referenceRect.height} preserveAspectRatio="none" />

            {mode === "copy" && geometryValidated && copy.visualization.regions.slice(0, 4).map((region, index) => {
              const color = REGION_COLORS[index % REGION_COLORS.length];
              const active = activeEvidence === region.id;
              return (
                <g key={region.id} className={`regionGroup ${active ? "active" : ""}`} onMouseEnter={() => setActiveEvidence(region.id)} onMouseLeave={() => setActiveEvidence(null)} onClick={() => setActiveEvidence(region.id)}>
                  <polygon points={polygonPoints(queryRect, region.query_polygon)} fill={color} stroke={color} className="regionPolygon" />
                  <polygon points={polygonPoints(referenceRect, region.reference_polygon)} fill={color} stroke={color} className="regionPolygon" />
                  <title>{`${region.label}: ${region.supporting_inliers} robust supporting inliers`}</title>
                </g>
              );
            })}

            {mode === "copy" && showFeaturePairs && geometryValidated && copy.visualization.correspondences.slice(0, 14).map((item, index) => {
              const queryPoint = mapPoint(queryRect, item.query);
              const referencePoint = mapPoint(referenceRect, item.reference);
              const active = activeEvidence === item.id;
              return (
                <g key={item.id} className={`correspondence ${active ? "active" : ""}`} onMouseEnter={() => setActiveEvidence(item.id)} onMouseLeave={() => setActiveEvidence(null)} onClick={() => setActiveEvidence(item.id)}>
                  {active && <line x1={queryPoint[0]} y1={queryPoint[1]} x2={referencePoint[0]} y2={referencePoint[1]} className="matchLine visible" />}
                  <circle cx={queryPoint[0]} cy={queryPoint[1]} r="9" className="matchPoint" />
                  <circle cx={referencePoint[0]} cy={referencePoint[1]} r="9" className="matchPoint" />
                  <text x={queryPoint[0]} y={queryPoint[1] + 3.5} textAnchor="middle" className="pairNumber">{index + 1}</text>
                  <text x={referencePoint[0]} y={referencePoint[1] + 3.5} textAnchor="middle" className="pairNumber">{index + 1}</text>
                  <title>{`Pair ${index + 1}: descriptor ${item.descriptor_distance}; transfer error ${metric(item.transfer_error_px)} px`}</title>
                </g>
              );
            })}

            {mode === "copy" && !geometryValidated && (
              <g>
                <rect x="650" y="250" width="200" height="86" rx="5" className="overlayUnavailable" />
                <text x="750" y="280" textAnchor="middle" className="overlayUnavailableTitle">NO RELIABLE MATCHED AREAS</text>
                <text x="750" y="304" textAnchor="middle" className="overlayUnavailableText">The local alignment was not strong enough.</text>
                <text x="750" y="322" textAnchor="middle" className="overlayUnavailableText">CreatorProof will not draw guessed points.</text>
              </g>
            )}

            {mode === "stylemap" && diagnostics && (
              <>
                {diagnostics.tile_map.query_cells.map((cell) => {
                  const rect = tileRect(cell, queryRect, diagnostics.tile_map.grid_size);
                  const active = activeStyleCell === cell.id;
                  return <rect key={cell.id} x={rect.x} y={rect.y} width={rect.width} height={rect.height} className={`styleHeatCell ${active ? "active" : ""}`} style={{ fillOpacity: 0.05 + cell.score * 0.48 }} onClick={() => setActiveStyleCell(cell.id)} onMouseEnter={() => setActiveStyleCell(cell.id)} />;
                })}
                {diagnostics.tile_map.reference_cells.map((cell) => {
                  const rect = tileRect(cell, referenceRect, diagnostics.tile_map.grid_size);
                  const active = activeStyleCell === cell.id;
                  return <rect key={cell.id} x={rect.x} y={rect.y} width={rect.width} height={rect.height} className={`styleHeatCell reference ${active ? "active" : ""}`} style={{ fillOpacity: 0.05 + cell.score * 0.48 }} onClick={() => setActiveStyleCell(cell.id)} onMouseEnter={() => setActiveStyleCell(cell.id)} />;
                })}
              </>
            )}
          </svg>
        </div>
          ))}

          {mode === "overview" && (
        <div className="modeExplanationGrid">
          <div><span>01</span><b>Was AI likely used?</b><p>Models, visible AI labels, and signed source information are checked independently from the catalog.</p></div>
          <div><span>02</span><b>Does it reuse a stored work?</b><p>The closest work is found first, then matching areas must pass strict checks before they are shown.</p></div>
          <div><span>03</span><b>Does it resemble a creator?</b><p>Different content can be compared with patterns learned from several registered creator works.</p></div>
          <div><span>04</span><b>Can the record be verified?</b><p>The result receives a tamper-evident receipt. Public blockchain proof is shown only when it is truly active.</p></div>
        </div>
          )}

          {mode === "overview" && (
            <div className={`proofReceiptPanel ${proofScope === "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY" ? "onchain" : "local"}`}>
              <div>
                <span>EVIDENCE COMMITMENT</span>
                <strong>{proof?.anchor_status ?? "NOT REQUESTED"}</strong>
                <small>{proof?.provider ?? "no proof provider"}</small>
              </div>
              <div>
                <span>COMMITMENT HASH</span>
                <code>{proof?.packet_hash_sha256 ?? "not available"}</code>
                <small>{proof?.commitment_scope ?? "no commitment scope"}</small>
              </div>
              <div>
                <span>VERIFICATION SCOPE</span>
                <strong>{proofScope === "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY" ? "PUBLIC EAS / EVM" : "LOCAL MERKLE LOG"}</strong>
                <small>{proofScope === "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY" ? "Mined transaction; media stays off-chain" : "Tamper-evident receipt; explicitly not blockchain"}</small>
                {explorerUrl ? <a href={explorerUrl} target="_blank" rel="noreferrer">Open transaction explorer ↗</a> : null}
              </div>
            </div>
          )}

          {mode === "structure" && (
        <div className="structureMetrics">
          <div><span>Luminance correlation</span><b>{metric(aligned?.luminance_correlation, 4)}</b><p>Brightness-pattern agreement after alignment; largely insensitive to global colour shifts.</p></div>
          <div><span>Gradient correlation</span><b>{metric(aligned?.gradient_correlation, 4)}</b><p>Whether edge-strength patterns occur in corresponding places.</p></div>
          <div><span>Gradient magnitude similarity</span><b>{metric(aligned?.gradient_magnitude_similarity, 4)}</b><p>Direct agreement of local edge energy, useful across compression and retouching.</p></div>
          <div><span>Local structural similarity</span><b>{metric(aligned?.structural_similarity, 4)}</b><p>Agreement of local luminance, contrast, and neighbourhood structure.</p></div>
          <div><span>Aligned overlap</span><b>{percent(aligned?.overlap_ratio)}</b><p>How much of the reference plane receives valid pixels after the verified transform.</p></div>
          <div><span>Colour similarity</span><b>{metric(aligned?.color_similarity, 4)}</b><p>Reported for context only. Colour changes do not veto preserved structural evidence.</p></div>
        </div>
          )}

          {mode === "copy" && (
        <div className="copyInspector">
          {activeCorrespondence ? (
            <>
              <div><span>Selected pair</span><b>{activeCorrespondence.id}</b></div>
              <div><span>Pattern difference</span><b>{activeCorrespondence.descriptor_distance}</b></div>
              <div><span>Placement error</span><b>{metric(activeCorrespondence.transfer_error_px, 3)} px</b></div>
              <p>Meaning: two small patterns look alike and move consistently when the images are aligned. One pair proves nothing; many well-spread pairs must agree.</p>
            </>
          ) : activeRegion ? (
            <>
              <div><span>Selected support envelope</span><b>{activeRegion.label}</b></div>
              <div><span>Supporting points</span><b>{activeRegion.supporting_inliers}</b></div>
              <div><span>Image area</span><b>{percent(activeRegion.query_coverage)}</b></div>
              <p>Meaning: this box contains several matching points. It is a support area, not the outline of a copied object.</p>
            </>
          ) : (
            <p>Hover a support envelope, or enable numbered feature pairs and inspect a number. The same number marks the measured location on both images; a connector appears only for the pair you inspect.</p>
          )}
        </div>
          )}

          {mode === "style" && diagnostics && styleProfile && (
        <div className="styleEvidencePanel">
          <div className="styleProfileCard">
            <span>CLOSEST CREATOR PROFILE</span>
            <h3>{styleProfile.creator}</h3>
            <div className="styleScoreRow"><b>{percent(styleEvidenceIndex)}</b><small>{styleDecision?.evidence_tier ?? "UNAVAILABLE"} resemblance evidence · not probability</small></div>
            <p>Compared with {styleProfile.sample_count} registered works from this creator. This is resemblance evidence, not proof that a style was copied.</p>
            <details className="technicalDisclosure styleTechnicalDisclosure">
              <summary>Show advanced creator-profile measurements</summary>
              <dl>
                <div><dt>Raw style-model score</dt><dd>{metric(rawStyleScore, 3)}</dd></div>
                <div><dt>Catalog rank score</dt><dd>{metric(styleProfile.csls_score, 3)}</dd></div>
                <div><dt>Same-content control</dt><dd>{metric(styleProfile.content_similarity, 3)}</dd></div>
                <div><dt>Style minus content</dt><dd>{metric(styleProfile.style_content_gap, 3)}</dd></div>
                <div><dt>Profile consistency</dt><dd>{metric(styleProfile.within_profile_cohesion, 3)}</dd></div>
                <div><dt>Catalog rank</dt><dd>#{styleProfile.readout_rank ?? "?"} · {percent(styleProfile.catalog_percentile)}</dd></div>
                <div><dt>False-match tail</dt><dd>{metric(styleDecision?.negative_tail_p, 4)}</dd></div>
                <div><dt>Positive support</dt><dd>{percent(styleDecision?.positive_support_percentile)}</dd></div>
              </dl>
              <small>{style.provider} · {style.calibration_state}</small>
            </details>
          </div>
          <div className="diagnosticCard"><span>WHAT LOOKS SIMILAR · NOT PROOF OF COPYING</span><FactorBars factors={diagnostics.factors} /></div>
          <div className="paletteCard">
            <span>CANDIDATE PALETTE</span><Palette colors={diagnostics.query_palette} />
            <span>EXEMPLAR PALETTE</span><Palette colors={diagnostics.reference_palette} />
            <small>Matching colours alone cannot establish creator-profile resemblance.</small>
          </div>
        </div>
          )}

          {mode === "style" && styleDecision && (
        <div className={`styleDecisionStrip ${tierClass(styleDecision.evidence_tier)}`}>
          <div><span>WHAT TO DO</span><b>{styleDecision.review_recommended ? "Ask a person to review this" : "No extra style review needed"}</b></div>
          <div><span>SAME IMAGE OR NEW CONTENT?</span><b>{styleDecision.content_confound_state === "CONTENT_CONFOUND_PRESENT" ? "May reuse the same content" : "Appears to be different content"}</b></div>
          <div><span>CHECKS THAT AGREED</span><b>{styleDecision.independent_support_count ?? 0} supporting checks</b></div>
          <details className="styleReasonDetails"><summary>Show machine codes</summary><p>{styleDecision.reason_codes?.join(" · ") || "No style reason codes recorded."}</p></details>
        </div>
          )}

          {mode === "stylemap" && selectedStyleCell && (
        <div className="tileInspector">
          <b>Tile {selectedStyleCell.row + 1}:{selectedStyleCell.column + 1}</b>
          <span>best cross-image tile {selectedStyleCell.best_partner.row + 1}:{selectedStyleCell.best_partner.column + 1}</span>
          <span>diagnostic {metric(selectedStyleCell.score)}</span>
          <span>palette {metric(selectedStyleCell.factors.palette)}</span>
          <span>tone {metric(selectedStyleCell.factors.tone)}</span>
          <span>edge {metric(selectedStyleCell.factors.stroke_orientation)}</span>
          <span>texture {metric(selectedStyleCell.factors.texture)}</span>
        </div>
          )}

          <div className="evidenceFooter">
            <div>
              <b>What this result can and cannot say</b>
              <p>
                A stored-work match means several checks agreed inside the selected catalog. It does not mean
                “legally infringing.” AI-use and creator resemblance are separate review signals and cannot turn
                themselves into a copy claim.
              </p>
              {fusion?.reason_codes?.length ? <small>{fusion.reason_codes.join(" · ")}</small> : null}
            </div>
            <div>
              <button type="button" className="aiExplainButton" onClick={explainEvidence} disabled={aiExplainState === "loading"}>
                {aiExplainState === "loading" ? "Explaining evidence…" : "Explain this case with OpenRouter"}
              </button>
              <small>OpenRouter explains the recorded metrics only. It cannot change retrieval, verification, style ranking, or policy.</small>
            </div>
          </div>
          {aiExplanation && <div className={`aiExplanation ${aiExplainState === "error" ? "error" : ""}`}>{aiExplanation}</div>}
        </div>
      </div>
    </section>
  );
}
