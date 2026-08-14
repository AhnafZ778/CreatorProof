"use client";

import { useState, type ReactNode } from "react";

import { OriginField } from "@/app/components/EvidenceCharts";
import { laneMetrics, usableMetric } from "@/app/lib/laneMetrics";
import { laneStatuses, type LaneKey, type LaneState, type LaneStatus } from "@/app/lib/laneStatus";
import { isPublicBlockchainProof } from "@/app/lib/verifyStatement";

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
  reflected?: boolean;
  alignment_grade?: "NONE" | "STRICT" | "CORROBORATION_REQUIRED";
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
  evaluation_mask_policy?: string;
  support_region_count?: number;
  support_overlap_ratio?: number;
  support_fraction_of_aligned_overlap?: number;
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
  ai_regional_similarity?: number | null;
  retrieval_view?: string;
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
  provider_role?: "PRIMARY" | "FALLBACK" | string;
  model_version?: string | null;
  source_scope?: string;
  evidence_family?: string;
  evidence_family_verified?: boolean;
  score_semantics?: string;
  calibrated: boolean;
  calibration_state?: string;
  aggregate_score: number;
  original_score?: number | null;
  global_delivery_score?: number | null;
  transformed_delivery_score?: number | null;
  spatial_consensus_score?: number | null;
  spatial_support_count?: number;
  spatial_corroborated?: boolean;
  view_standard_deviation?: number | null;
  transform_stability?: number | null;
  transform_stability_state?: string;
  aggregation_strategy?: string;
  inference_mode?: string;
  provider_details?: {
    model?: string | null;
    request_id?: string | null;
    operations?: number | null;
    global_ai_generated_score?: number | null;
    generator_scores?: Record<string, number>;
    secondary_scores?: Record<string, number>;
    input_mode?: string | null;
    explanation_scope?: string | null;
  };
  warnings?: string[];
};

type OriginForensicIndicators = {
  generator_cues?: Array<{
    provider: string;
    role?: string;
    generator: string;
    score: number;
    ai_confidence?: number | null;
    assessment?: string;
  }>;
  provider_explanations?: Array<{
    provider: string;
    role?: string;
    input_mode?: string | null;
    global_ai_signal?: number | null;
    generator_score_count?: number;
    explanation_scope?: string;
  }>;
  spatial_hotspots?: Array<Record<string, unknown>>;
  transformation_resilience?: Array<Record<string, unknown>>;
  limitation?: string;
};

type SyntheticRuntime = {
  routing?: {
    primary_provider?: string | null;
    primary_attempted?: boolean;
    primary_succeeded?: boolean;
    fallback_activated?: boolean;
    fallback_reason?: string | null;
    fallback_providers?: string[];
  };
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

type OriginScorecard = {
  signal_score: number;
  signal_label: string;
  evidence_quality_score: number;
  evidence_quality_label: string;
  score_semantics: string;
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
  forensic_indicators?: OriginForensicIndicators;
  runtime?: SyntheticRuntime;
  reason_codes?: string[];
  limitations?: string[];
};

type ProofData = {
  anchor_status?: string;
  provider?: string;
  proof_kind?: string;
  anchor_scope?: string;
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
    guidance: "Read the AI signal and evidence quality together to understand the strength of the origin-analysis result.",
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
    guidance: "This detail view maps visual qualities across palette, tone, edge direction, and texture.",
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

function fitImage(size: [number, number] | undefined, box: typeof QUERY_BOX): ImageRect {
  if (!size) return { ...box };
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
      summary: "The image contains a visible label that identifies AI use.",
      action: "Inspect the highlighted label alongside the full CreatorProof evidence packet.",
    };
  }
  if (classification === "AI_ORIGIN_REVIEW_CANDIDATE") {
    return {
      state: "AI_INDICATORS_NEED_REVIEW",
      tone: "review",
      headline: "AI-generation indicators found",
      summary: "The analysis engine surfaced signals that deserve focused review.",
      action: "Inspect the origin signals and continue through the full CreatorProof decision path.",
    };
  }
  if (classification === "NO_AI_ORIGIN_EVIDENCE_DETECTED") {
    return {
      state: "NO_STRONG_AI_SIGNAL",
      tone: "low",
      headline: "AI-origin analysis complete",
      summary: "Active origin checks completed without a high-confidence AI-generation signal.",
      action: "Continue with visual matching, creator intelligence, and the recorded rights path.",
    };
  }
  if (classification === "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE") {
    return {
      state: "CHECK_UNAVAILABLE",
      tone: "unavailable",
      headline: "AI-origin analysis needs activation",
      summary: "This scan did not receive an origin-analysis result.",
      action: "Open System intelligence to activate the AI-origin analysis route.",
    };
  }
  if (classification === "AI_ORIGIN_CHECK_DISABLED") {
    return {
      state: "CHECK_DISABLED",
      tone: "unavailable",
      headline: "AI-origin analysis is policy-controlled",
      summary: "This review follows the configured CreatorProof policy.",
      action: "Continue with visual matching and the recorded rights path.",
    };
  }
  return {
    state: "ORIGIN_UNKNOWN",
    tone: "inconclusive",
    headline: "AI-origin analysis surfaced mixed signals",
    summary: "CreatorProof has prepared this case for focused evidence review.",
    action: "Inspect the origin signal breakdown and continue through the CreatorProof decision path.",
  };
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
      headline: "Add protected works to activate catalog matching",
      detail: "This catalog is ready for reference registration and visual matching.",
    };
  }
  if (status === "TRUNCATED") {
    return {
      tone: "incomplete",
      headline: "Additional candidate verification is available",
      detail: "Open the source record to continue the configured verification plan.",
    };
  }
  if (status === "DEGRADED") {
    return {
      tone: "incomplete",
      headline: "Enhanced retrieval is ready for activation",
      detail: "Open System intelligence to complete the configured retrieval stack.",
    };
  }
  if (status === "PARTIAL") {
    return {
      tone: "incomplete",
      headline: "Candidate verification is ready to continue",
      detail: "Open the source record to complete the next verification step.",
    };
  }
  if (status === "FAILED") {
    return {
      tone: "failed",
      headline: "Stored-work verification needs a fresh run",
      detail: "Restart the scan to generate a complete visual-matching record.",
    };
  }
  return {
    tone: "incomplete",
    headline: "Source coverage details are being prepared",
    detail: "Open the source record to inspect the active catalog scope.",
  };
}

/**
 * The catalog this run actually searched, stated once as a quiet line.
 *
 * How much of the catalog was covered is already answered by the donut in the
 * verdict, so the counts are deliberately not repeated here. What is left is
 * the part no chart can carry: which catalog, which version, which snapshot —
 * the identifiers someone re-running this scan would need to reproduce it.
 */
function ScopeBanner({ scope }: { scope: EvidenceScope | undefined }) {
  const presentation = scopePresentation(scope);
  const eligible = scope?.eligible_reference_count ?? 0;
  const reasons = scope?.coverage_reason_codes ?? [];
  return (
    <details className={`scopeAudit ${presentation.tone}`}>
      <summary>
        <span className="scopeAuditDot" aria-hidden="true" />
        <b>{scope?.catalog_id ?? "Catalog not recorded"}</b>
        <em>{eligible} eligible {eligible === 1 ? "work" : "works"} searched</em>
        <i>{scope?.coverage_status ?? "UNAVAILABLE"}</i>
      </summary>
      <div className="scopeAuditGrid">
        <span>Catalog version</span><code>{scope?.catalog_version ?? "not recorded"}</code>
        <span>Snapshot</span><code>{scope?.snapshot_id ?? "not recorded"}</code>
        <span>Retrieval requirement</span><b>{scope?.retrieval_requirement ?? "not recorded"}</b>
        <span>Learned descriptors</span><b>{scope?.descriptor_coverage?.available_reference_count ?? 0}/{eligible}</b>
        <span>Coverage reasons</span><b>{reasons.length ? reasons.join(" · ") : "NONE"}</b>
      </div>
    </details>
  );
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

/* ── One anatomy for all three lane explanations ────────────────────────────
   The lanes answer different questions from different evidence, but a reader
   who has learnt to read one panel should not have to learn the other two. So
   the shape is fixed — verdict, reading, next step — and only the middle
   changes. The verdict wording comes from `laneStatus.ts`, the same derivation
   the summary cards use, so a panel can never contradict the card that sent
   the reader to it. */

const LANE_TAG: Record<LaneState, string> = {
  hit: "FOUND",
  review: "REVIEW",
  clear: "CLEAR",
  advisory: "CONTEXT",
  unchecked: "NO RESULT",
};

function LaneVerdict({
  state,
  headline,
  summary,
}: {
  state: LaneState;
  headline: string;
  summary: string;
}) {
  return (
    <header className="laneVerdict">
      <em>{LANE_TAG[state]}</em>
      <h4>{headline}</h4>
      <p>{summary}</p>
    </header>
  );
}

function LaneNextStep({ children }: { children: ReactNode }) {
  return (
    <div className="laneNextStep">
      <b>NEXT STEP</b>
      <span>{children}</span>
    </div>
  );
}

/**
 * The one action a lane result calls for.
 *
 * A lane that found nothing still needs a closing line, because silence there
 * invites the reader to supply their own conclusion — usually a broader
 * clearance than the scan can support. `lane.note` carries that boundary for
 * the lanes that could not run, so it is preferred over anything written here.
 */
const LANE_ACTION: Record<LaneKey, Partial<Record<LaneState, string>>> = {
  copy: {
    hit: "Treat this as reuse of a registered work and settle rights with the claimant before publishing.",
    review: "Have a person compare the two images before publishing; the evidence supports review, not a conclusion.",
    clear: "Nothing to settle here — though this covers only the catalog named above.",
  },
  profile: {
    advisory: "Read this as context for a human decision. Resemblance to a creator’s body of work is not by itself an infringement finding.",
    clear: "No creator-profile follow-up needed for this candidate.",
  },
  origin: {},
  rights: {},
};

function laneNextStep(lane: LaneStatus): string {
  return LANE_ACTION[lane.key][lane.state] ?? lane.note;
}

/**
 * A lane that has no picture to show, saying why.
 *
 * There are two very different reasons a comparison is missing and they call
 * for opposite responses, so they are never merged into one message: either the
 * lane genuinely found nothing to draw, which is a result, or the plates have
 * not arrived in this browser, which is a loading state. Reading the first as
 * the second is what made an empty catalog look like a clean scan.
 */
function LaneEmpty({
  laneKey,
  hasEvidence,
  scope,
  candidateReady,
}: {
  laneKey: LaneKey;
  hasEvidence: boolean;
  scope: EvidenceScope | undefined;
  candidateReady: boolean;
}) {
  if (hasEvidence) {
    return (
      <div className="microscopeEmpty">
        <b>{candidateReady ? "Reference image not loaded" : "Images not loaded"}</b>
        <span>
          This lane has a result, but the pictures behind it are not in this browser session.
          Re-run the scan to see the side-by-side comparison.
        </span>
      </div>
    );
  }

  const eligible = scope?.eligible_reference_count ?? 0;
  if (laneKey === "copy") {
    return (
      <div className="microscopeEmpty">
        <b>Nothing to compare against</b>
        <span>
          {eligible === 0
            ? "This catalog holds no eligible reference, so there was no stored work to line the candidate up against. Register work in the Artist portal under the same catalog name, then scan again."
            : `${eligible} ${eligible === 1 ? "work was" : "works were"} searched and none matched closely enough to align, so there is no overlay to draw. The verdict above is the result.`}
        </span>
      </div>
    );
  }

  return (
    <div className="microscopeEmpty">
      <b>No creator profile to compare against</b>
      <span>
        A profile is built from several works by one claimant. Register at least three works under
        the same claimant to activate this lane; until then it has nothing to measure resemblance
        against.
      </span>
    </div>
  );
}

/** The engine's evidence tier, said the way a person would say it. */
function tierPhrase(tier: string | undefined): string {
  switch ((tier ?? "").toUpperCase()) {
    case "VERY_HIGH": return "Very strong evidence";
    case "HIGH": return "Strong evidence";
    case "REVIEW": return "Enough to review";
    case "ADVISORY_ONLY": return "Context only, not a finding";
    case "LOW": return "Below the review bar";
    case "": case "UNAVAILABLE": return "No tier recorded";
    default: return (tier ?? "").replaceAll("_", " ").toLowerCase();
  }
}

/**
 * A labelled quantity, sized to be read before the words around it.
 *
 * `variant="name"` is for the one figure that answers with a name rather than
 * a number — a creator, not a score. It drops the tabular mono face, which
 * turns a name into something that looks measured.
 */
function LaneFigure({
  label,
  value,
  unit,
  meaning,
  note,
  variant,
}: {
  label: string;
  value: string;
  unit?: string;
  meaning: string;
  note: string;
  variant?: "name";
}) {
  return (
    <div className={`laneFigure${variant === "name" ? " isName" : ""}`}>
      <span>{label}</span>
      <b>{value}{unit ? <small>{unit}</small> : null}</b>
      <strong>{meaning}</strong>
      <p>{note}</p>
    </div>
  );
}

function OriginSummary({
  synthetic,
  presentation,
  candidate,
  policyMode,
  state,
}: {
  synthetic: SyntheticOrigin | undefined;
  presentation: SyntheticPresentation;
  candidate: LocalImagePreview | null;
  policyMode: string;
  state: LaneState;
}) {
  const scorecard = synthetic?.scorecard;
  const routing = synthetic?.runtime?.routing;
  const generatorCues = (synthetic?.forensic_indicators?.generator_cues ?? []).slice(0, 6);
  const routeHeadline = routing?.primary_succeeded
    ? "Primary AI analysis complete"
    : routing?.fallback_activated
      ? "Continuity AI analysis complete"
      : synthetic?.members?.length
        ? "AI analysis complete"
        : "AI analysis pending";
  const routeDetail = routing?.primary_succeeded
    ? "The original submitted image was analyzed through the primary intelligence route."
    : routing?.fallback_activated
      ? "The active continuity route completed the origin analysis."
      : "Provider route and analysis status are available in advanced details.";
  // A missing score is not a zero. `fused_detector_score` of null means the
  // route never returned a reading, and plotting that at the origin would put
  // the scan in the same place as a genuine "no AI signal found".
  const signalScore =
    scorecard?.signal_score ??
    (synthetic?.fused_detector_score == null ? null : Math.round(synthetic.fused_detector_score * 100));
  const qualityScore = scorecard?.evidence_quality_score ?? null;

  return (
    <div className="lanePanel lane-origin" data-state={state} role="status" aria-atomic="true">
      <LaneVerdict state={state} headline={presentation.headline} summary={presentation.summary} />

      <div className="laneReading originReading">
        <OriginImageCard candidate={candidate} markerSignal={synthetic?.visible_marker_signal} />

        <figure className="originFieldWrap">
          <OriginField signal={signalScore} quality={qualityScore} />
          <figcaption>
            A finding needs both: a signal the models can see, and evidence good
            enough to trust it. Low on either axis is not a clearance.
          </figcaption>
        </figure>

        <div className="laneFigures">
          <LaneFigure
            label="AI SIGNAL"
            value={signalScore === null ? "—" : String(signalScore)}
            unit={signalScore === null ? undefined : "/100"}
            // A low signal only means "no AI" when the evidence behind it is
            // good. Where the lane could not conclude, the engine's own label
            // would over-read the number, so the caveat replaces it.
            meaning={
              state === "unchecked"
                ? "Not conclusive on its own"
                : (scorecard?.signal_label ?? (signalScore === null ? "No reading returned" : "Signal not fully scored"))
            }
            note={
              state === "unchecked"
                ? "A reading this weak needs evidence quality behind it before it means anything."
                : "How much the active models saw."
            }
          />
          <LaneFigure
            label="EVIDENCE QUALITY"
            value={qualityScore === null ? "—" : String(qualityScore)}
            unit={qualityScore === null ? undefined : "/100"}
            meaning={scorecard?.evidence_quality_label ? `${scorecard.evidence_quality_label} analysis quality` : "No reading returned"}
            note="How far that reading can be trusted."
          />
        </div>
      </div>

      <LaneNextStep>{presentation.action}</LaneNextStep>

      {generatorCues.length > 0 && (
        <section className="originCluePanel" aria-label="AI detector clues">
          <div>
            <span>AI SIGNAL CLUES</span>
            <h5>What contributed to the AI signal</h5>
          </div>
          <div className="originClueGrid">
            {generatorCues.map((cue) => (
              <div key={`${cue.provider}-${cue.generator}`}>
                <span>{cue.provider} · {cue.role ?? "detector"}</span>
                <b>{cue.generator === "GLOBAL_AI_GENERATED_SIGNAL" ? "Overall AI signal" : cue.generator.replaceAll("_", " ")}</b>
                <strong>{percent(cue.score)}</strong>
              </div>
            ))}
          </div>
          <small>{synthetic?.forensic_indicators?.limitation}</small>
        </section>
      )}
      <details className="technicalDisclosure originTechnicalDisclosure">
        <summary>Show advanced details for judges and engineers</summary>
        <p className="technicalIntro">
          These are machine diagnostics. Raw model values are not percentages or universal
          probabilities, and a quiet result never proves human origin.
        </p>
        <div className="originRunContext">
          <div>
            <span>ANALYSIS ROUTE</span>
            <b>{routeHeadline}</b>
            <small>{routeDetail}</small>
          </div>
          <div>
            <span>WORKFLOW POLICY</span>
            <b>{policyMode}</b>
            <small>
              {policyMode === "REQUIRED"
                ? "AI-origin intelligence is included in the configured decision flow."
                : policyMode === "DISABLED"
                  ? "This review follows the configured CreatorProof policy."
                  : "Recorded alongside visual matching, creator intelligence, and rights context."}
            </small>
          </div>
        </div>
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
          <div className="detectorLedgerHead"><span>MODEL / ROUTE</span><span>RAW SIGNAL</span><span>CONSISTENCY</span><span>TESTING STATE</span></div>
          {synthetic?.members?.length ? synthetic.members.map((member) => (
            <div key={`${member.provider}-${member.model_version ?? "unknown"}`}>
              <span><b>{member.provider}</b><small>{member.provider_role ?? "LOCAL"} · {member.evidence_family ?? member.model_version ?? "family unspecified"}</small></span>
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
      ) : <p>Image preview is not available in this browser session.</p>}
      {markers.length ? (
        <p className="markerFoundNote"><b>Visible AI label highlighted.</b> Included in the full CreatorProof evidence readout.</p>
      ) : (
        <p>AI-origin intelligence runs independently from stored-work matching and creator-profile analysis.</p>
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
  const lanes = laneStatuses(scan);
  const metrics = laneMetrics(scan);
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

  // A lane with nothing to draw is still a lane with a verdict. Every view stays
  // reachable and states its own result, because collapsing the workspace to
  // whichever lane happened to return imagery left the other two looking as
  // though they had never been asked.
  const visualization = copy?.visualization ?? null;
  const hasCopyEvidence = Boolean(visualization);
  const hasStyleEvidence = Boolean(styleProfile);

  const fusion = copy?.fusion;
  const aligned = copy?.aligned_perceptual;
  const styleMode = mode === "style" || mode === "stylemap";
  const reference = styleMode ? styleReference : copyReference;
  const querySize = styleMode && diagnostics ? diagnostics.query_size : visualization?.query_size;
  const referenceSize = styleMode && diagnostics ? diagnostics.reference_size : visualization?.reference_size;
  const queryRect = fitImage(querySize, QUERY_BOX);
  const referenceRect = fitImage(referenceSize, REFERENCE_BOX);
  const geometryValidated = Boolean(copy?.geometry.validated || copy?.exact_sha256);
  // Flat and repetitive art can only be aligned under relaxed matching, which
  // the pixel check then confirms. Reading that as "rejected" would contradict
  // the match sitting next to it.
  const geometryRecovered = copy?.geometry.alignment_grade === "CORROBORATION_REQUIRED";
  const geometryMirrored = Boolean(copy?.geometry.reflected);
  // A recovered alignment still produces matched points and support regions, so
  // it has something to draw even though it did not verify on its own.
  const geometryAligned = geometryValidated || geometryRecovered;
  // The comparison needs both plates and a measured geometry to place them
  // against. Style views substitute the tile map, so they carry their own test.
  const laneHasEvidence = styleMode ? hasStyleEvidence : hasCopyEvidence;
  const canShowImages = Boolean(candidate?.url && reference?.url && laneHasEvidence);
  const activeCorrespondence = visualization?.correspondences.find((item) => item.id === activeEvidence);
  const activeRegion = visualization?.regions.find((item) => item.id === activeEvidence);
  const allStyleCells = diagnostics ? [...diagnostics.tile_map.query_cells, ...diagnostics.tile_map.reference_cells] : [];
  const selectedStyleCell = allStyleCells.find((item) => item.id === activeStyleCell) ?? null;
  const styleDecision = style?.decision;
  const styleEvidenceIndex = styleDecision?.evidence_index;
  const rawStyleScore = styleProfile?.raw_pool_similarity ?? styleProfile?.profile_similarity ?? styleProfile?.prototype_similarity;
  const activeMode = MODE_META[mode];
  const chainProof = isPublicBlockchainProof(proof);

  // Which lane the open view belongs to. The two detail views are deeper
  // readings of their parent lane, not lanes of their own, so they inherit its
  // verdict rather than implying a second, separate finding.
  const activeLaneKey = styleMode ? "profile" : "copy";
  const activeLane = lanes[activeLaneKey];
  const isDetailView = mode === "structure" || mode === "stylemap";
  const copyFigure = usableMetric(metrics.copy, lanes.copy.state);
  const profileFigure = usableMetric(metrics.profile, lanes.profile.state);
  const laneAction = laneNextStep(activeLane);

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
            copy_lane: copy
              ? {
                  title: copy.title,
                  verification_state: copy.verification_state,
                  fusion: copy.fusion,
                  ai_similarity: copy.ai_similarity,
                  ai_regional_similarity: copy.ai_regional_similarity,
                  retrieval_view: copy.retrieval_view,
                  geometry: copy.geometry,
                  aligned_perceptual: copy.aligned_perceptual,
                }
              : null,
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

  // The verdict above already states the coverage, the outcome and the four
  // lane answers. This section answers the next question instead — why — and
  // opens straight onto the working views rather than re-summarising them.
  return (
    <section id="analysis" className={`microscope mode-${mode}`} aria-label="Evidence workspace">
      <ScopeBanner scope={scope} />

      <div className="analysisWorkbench">
        <aside className="analysisSidebar" aria-label="Analysis navigation">
          <div className="analysisSidebarHeading">
            <small>4 SIMPLE VIEWS</small>
            <strong>What do you want to know?</strong>
            <p>Start with the summary. Detailed measurements stay inside their related view.</p>
          </div>
          <div className="modeRail" role="group" aria-label="Evidence visualization mode">
            {/* Every lane stays open. A lane with no evidence still has a
                verdict, and hiding the way in behind a disabled button left the
                reader unable to check whether it had even been asked. */}
            {PRIMARY_MODES.map((item) => {
              const meta = MODE_META[item];
              return (
                <button
                  key={item}
                  type="button"
                  className={`modeButton modeButton-${item} ${mode === item ? "active" : ""}`}
                  aria-pressed={mode === item}
                  onClick={() => {
                    setMode(item);
                    setActiveEvidence(null);
                    setActiveStyleCell(null);
                  }}
                >
                  <span className="modeNumber">{meta.number}</span>
                  <span className="modeCopy"><small>{meta.lane}</small><b>{meta.label}</b><em>{meta.short}</em></span>
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
            {/* The question. The panel underneath is the answer, so the
                guidance paragraph that used to sit here has moved into the
                panel's own summary rather than pre-empting it. */}
            <div>
              <small>{activeMode.lane}</small>
              <h3>{activeMode.label}</h3>
            </div>
            <div className="modeAction">
              {/* The detail views read the alignment, so they only exist once
                  there is one. Offering them against an empty lane would open a
                  screen of dashes. */}
              {mode === "copy" && hasCopyEvidence ? (
                <div className="modeActionButtons">
                  <button type="button" className={showFeaturePairs ? "active" : ""} disabled={!geometryAligned} onClick={() => setShowFeaturePairs((current) => !current)}>
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
              ) : mode !== "overview" && mode !== "origin" && !laneHasEvidence ? (
                <span className="modeReady isEmpty"><i /> NOTHING TO DRAW</span>
              ) : (
                <span className="modeReady"><i /> VIEW READY</span>
              )}
            </div>
          </div>

          {mode === "origin" && (
            <div className="originWorkbench">
              <OriginSummary
                synthetic={synthetic}
                presentation={originPresentation}
                candidate={candidate}
                policyMode={originPolicyMode}
                state={lanes.origin.state}
              />
            </div>
          )}

          {mode !== "origin" && (
          <div className={`lanePanel lane-${activeLaneKey}`} data-state={activeLane.state} role="status" aria-atomic="true">
          <LaneVerdict
            state={activeLane.state}
            headline={activeLane.headline}
            summary={isDetailView ? activeMode.guidance : activeLane.answer}
          />

          {(!canShowImages ? (
        <LaneEmpty
          laneKey={activeLaneKey}
          hasEvidence={laneHasEvidence}
          scope={scope}
          candidateReady={Boolean(candidate?.url)}
        />
      ) : (
        <div className="evidenceCanvasWrap">
          <svg className="evidenceCanvas" viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`} role="img" aria-label="Side-by-side CreatorProof evidence comparison">
            <text x="30" y="42" className="canvasHeading">CANDIDATE</text>
            <text x="1470" y="42" textAnchor="end" className="canvasHeading">{styleMode ? "STYLE EXEMPLAR" : "VERIFIED BEST REFERENCE"}</text>
            <text x="30" y="68" className="canvasFilename">{candidate?.name}</text>
            <text x="1470" y="68" textAnchor="end" className="canvasFilename">{reference?.name}</text>
            <text x="750" y="42" textAnchor="middle" className="canvasCenterLabel">
              {styleMode ? "STYLE / NO GEOMETRY IMPLIED" : `RETRIEVAL #${copy?.retrieval_rank ?? "?"} (${copy?.retrieval_view ?? "whole_image"}) → VERIFICATION #${copy?.verification_rank ?? 1}`}
            </text>
            <rect className="imageFrame" x={queryRect.x} y={queryRect.y} width={queryRect.width} height={queryRect.height} rx="3" />
            <rect className="imageFrame" x={referenceRect.x} y={referenceRect.y} width={referenceRect.width} height={referenceRect.height} rx="3" />
            <image href={candidate?.url} x={queryRect.x} y={queryRect.y} width={queryRect.width} height={queryRect.height} preserveAspectRatio="none" />
            <image href={reference?.url} x={referenceRect.x} y={referenceRect.y} width={referenceRect.width} height={referenceRect.height} preserveAspectRatio="none" />

            {mode === "copy" && geometryAligned && visualization?.regions.slice(0, 4).map((region, index) => {
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

            {mode === "copy" && showFeaturePairs && geometryAligned && visualization?.correspondences.slice(0, 14).map((item, index) => {
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

            {mode === "copy" && !geometryAligned && (
              <g>
                <rect x="650" y="250" width="200" height="86" rx="5" className="overlayUnavailable" />
                <text x="750" y="280" textAnchor="middle" className="overlayUnavailableTitle">MATCHED-AREA VIEW READY WHEN EVIDENCE IS FOUND</text>
                <text x="750" y="304" textAnchor="middle" className="overlayUnavailableText">No matched regions reached the visual-evidence threshold.</text>
                <text x="750" y="322" textAnchor="middle" className="overlayUnavailableText">Explore the summary or another evidence lane.</text>
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

          {mode === "structure" && (
        <div className="laneReading structureMetrics">
          <div><span>Luminance correlation</span><b>{metric(aligned?.luminance_correlation, 4)}</b><p>Brightness-pattern agreement after alignment; largely insensitive to global colour shifts.</p></div>
          <div><span>Gradient correlation</span><b>{metric(aligned?.gradient_correlation, 4)}</b><p>Whether edge-strength patterns occur in corresponding places.</p></div>
          <div><span>Gradient magnitude similarity</span><b>{metric(aligned?.gradient_magnitude_similarity, 4)}</b><p>Direct agreement of local edge energy, useful across compression and retouching.</p></div>
          <div><span>Local structural similarity</span><b>{metric(aligned?.structural_similarity, 4)}</b><p>Agreement of local luminance, contrast, and neighbourhood structure.</p></div>
          <div><span>Aligned overlap</span><b>{percent(aligned?.overlap_ratio)}</b><p>How much of the reference plane receives valid pixels after the verified transform.</p></div>
          <div><span>Colour similarity</span><b>{metric(aligned?.color_similarity, 4)}</b><p>Reported for context only. Colour changes do not veto preserved structural evidence.</p></div>
        </div>
          )}

          {/* Measurements only where there was something to measure. With no
              aligned candidate these read 0/0 and "geometry rejected", which
              describes an alignment that was never attempted. */}
          {mode === "copy" && hasCopyEvidence && (
        <div className="laneReading">
          <div className="laneFigures laneFiguresRow">
            <LaneFigure
              label="COPY EVIDENCE"
              value={copyFigure.display}
              meaning={tierPhrase(fusion?.evidence_tier)}
              note={copyFigure.withheld ?? copyFigure.qualifier ?? "How strongly the two images agree once aligned."}
            />
            <LaneFigure
              label="VERIFIED POINTS"
              value={String(copy?.geometry.inliers ?? 0)}
              unit={`/${copy?.geometry.tentative_matches ?? 0}`}
              meaning={geometryValidated ? "Geometry verified" : geometryRecovered ? "Alignment recovered" : "Geometry rejected"}
              note="Candidate point pairs that survived the alignment test."
            />
            <LaneFigure
              label="ALIGNED OVERLAP"
              value={aligned?.available ? percent(aligned.overlap_ratio) : "—"}
              meaning={
                aligned?.available
                  ? `${aligned.support_region_count ?? visualization?.regions.length ?? 0} support ${(aligned.support_region_count ?? visualization?.regions.length ?? 0) === 1 ? "region" : "regions"}`
                  : "No alignment to measure"
              }
              note="How much of the reference the candidate covers once aligned."
            />
          </div>
          <p className="laneInspector">
            {activeCorrespondence ? (
              <>
                <b>Pair {activeCorrespondence.id}</b>
                pattern difference {activeCorrespondence.descriptor_distance}, placement error {metric(activeCorrespondence.transfer_error_px, 3)} px.
                Two small patterns look alike and move together when the images are aligned. One pair proves nothing; many well-spread pairs must agree.
              </>
            ) : activeRegion ? (
              <>
                <b>{activeRegion.label}</b>
                {activeRegion.supporting_inliers} supporting points over {percent(activeRegion.query_coverage)} of the image.
                This is a support area, not the outline of a copied object.
              </>
            ) : (
              <>
                <b>Inspect the evidence</b>
                Hover a coloured envelope to see the points inside it, or turn on numbered pairs and hover a number — the same number marks the measured location in both images.
              </>
            )}
          </p>
        </div>
          )}

          {mode === "style" && styleProfile && (
        <div className="laneReading styleReading">
          <div className="laneFigures">
            <LaneFigure
              variant="name"
              label="CLOSEST PROFILE"
              value={styleProfile.creator}
              meaning={`${styleProfile.sample_count} registered ${styleProfile.sample_count === 1 ? "work" : "works"} in the profile`}
              note="A profile is built from several works, so one shared subject cannot carry it."
            />
            <LaneFigure
              label="RESEMBLANCE"
              value={profileFigure.display}
              meaning={tierPhrase(styleDecision?.evidence_tier)}
              note={profileFigure.withheld ?? profileFigure.qualifier ?? "Weighted across palette, tone, edge direction, and texture."}
            />
            <LaneFigure
              label="INDEPENDENT SUPPORT"
              value={String(styleDecision?.independent_support_count ?? 0)}
              meaning={
                styleDecision?.content_confound_state === "CONTENT_CONFOUND_PRESENT"
                  ? "May reuse the same content"
                  : "Different content, so style stands alone"
              }
              note="Separate checks that agreed before this lane would speak."
            />
          </div>
          {diagnostics && (
            <div className="styleVisuals">
              <figure>
                <figcaption>WHAT LOOKS VISUALLY SIMILAR</figcaption>
                <FactorBars factors={diagnostics.factors} />
              </figure>
              <figure>
                <figcaption>PALETTE</figcaption>
                <div className="palettePair">
                  <div><small>Candidate</small><Palette colors={diagnostics.query_palette} /></div>
                  <div><small>Exemplar</small><Palette colors={diagnostics.reference_palette} /></div>
                </div>
                <p>Palette is read alongside tone, texture, and visual structure — never on its own.</p>
              </figure>
            </div>
          )}
        </div>
          )}

          {mode === "stylemap" && (
        <div className="laneReading">
          <p className="laneInspector">
            {selectedStyleCell ? (
              <>
                <b>Tile {selectedStyleCell.row + 1}:{selectedStyleCell.column + 1}</b>
                closest cross-image partner is tile {selectedStyleCell.best_partner.row + 1}:{selectedStyleCell.best_partner.column + 1} —
                palette {metric(selectedStyleCell.factors.palette)}, tone {metric(selectedStyleCell.factors.tone)},
                edge {metric(selectedStyleCell.factors.stroke_orientation)}, texture {metric(selectedStyleCell.factors.texture)}.
              </>
            ) : (
              <>
                <b>Inspect a tile</b>
                Hover any tile to see which tile in the other image it most resembles, and which visual qualities drove that pairing.
              </>
            )}
          </p>
        </div>
          )}

          <LaneNextStep>{laneAction}</LaneNextStep>

          {mode === "style" && styleProfile && (
            <details className="technicalDisclosure">
              <summary>Show advanced creator-profile measurements</summary>
              <p className="technicalIntro">
                Machine diagnostics. These are ranking quantities rather than probabilities, and
                the engine gates its tiers on calibration and independent support rather than on
                any single value here.
              </p>
              <dl className="laneMeasurements">
                <div><dt>Raw style-model score</dt><dd>{metric(rawStyleScore, 3)}</dd></div>
                <div><dt>Catalog rank score</dt><dd>{metric(styleProfile.csls_score, 3)}</dd></div>
                <div><dt>Same-content control</dt><dd>{metric(styleProfile.content_similarity, 3)}</dd></div>
                <div><dt>Style minus content</dt><dd>{metric(styleProfile.style_content_gap, 3)}</dd></div>
                <div><dt>Profile consistency</dt><dd>{metric(styleProfile.within_profile_cohesion, 3)}</dd></div>
                <div><dt>Catalog rank</dt><dd>#{styleProfile.readout_rank ?? "?"} · {percent(styleProfile.catalog_percentile)}</dd></div>
                <div><dt>False-match tail</dt><dd>{metric(styleDecision?.negative_tail_p, 4)}</dd></div>
                <div><dt>Positive support</dt><dd>{percent(styleDecision?.positive_support_percentile)}</dd></div>
                <div><dt>Raw evidence index</dt><dd>{metric(styleEvidenceIndex, 3)}</dd></div>
              </dl>
              <small>
                {style?.provider} · {style?.calibration_state}
                {styleDecision?.reason_codes?.length ? ` · ${styleDecision.reason_codes.join(" · ")}` : ""}
              </small>
            </details>
          )}
          </div>
          )}

          <div className="evidenceFooter">
            <div>
              <b>Why the engine ruled this way</b>
              {fusion?.reason_codes?.length
                ? <small>{fusion.reason_codes.join(" · ")}</small>
                : <p>This run recorded no fusion reason codes.</p>}
            </div>
            <div>
              <button type="button" className="aiExplainButton" onClick={explainEvidence} disabled={aiExplainState === "loading"}>
                {aiExplainState === "loading" ? "Preparing case explanation…" : "Explain this case in plain English"}
              </button>
            </div>
          </div>
          {aiExplanation && <div className={`aiExplanation ${aiExplainState === "error" ? "error" : ""}`}>{aiExplanation}</div>}
        </div>
      </div>

      {/* Raw signals last. Anyone who wants the underlying numbers has read the
          views by now; anyone who does not should never have been shown them. */}
      <details className="technicalDisclosure signalDisclosure">
        <summary>Show the raw signals behind these views</summary>
        <div className="signalMatrix" aria-label="Technical evidence signals">
          <div className="signalCard originSignal"><i /><span>Independent AI checks</span><b>{synthetic?.evidence_family_count ?? 0} types</b><small>{synthetic?.classification ?? "unavailable"}</small></div>
          <div className="signalCard retrievalSignal"><i /><span>SSCD nomination</span><b>{metric(copy?.retrieval_score ?? copy?.ai_similarity, 3)}</b><small>{copy?.retrieval_view ?? "whole_image"} · whole {metric(copy?.ai_similarity, 3)} · regional {metric(copy?.ai_regional_similarity, 3)}</small></div>
          <div className="signalCard geometrySignal"><i /><span>Local geometry</span><b>{geometryValidated ? metric(fusion?.geometry_quality, 3) : geometryRecovered ? "recovered" : "rejected"}</b><small>{copy?.geometry.inliers ?? 0}/{copy?.geometry.tentative_matches ?? 0} verified inliers{geometryMirrored ? " · mirrored" : ""}{geometryRecovered ? " · confirmed by aligned pixels" : ""}</small></div>
          <div className="signalCard structureSignal"><i /><span>Aligned structure</span><b>{metric(aligned?.structure_consensus, 3)}</b><small>{aligned?.evaluation_mask_policy ?? fusion?.signal_states?.aligned_structure ?? aligned?.reason ?? "not measured"} · {aligned?.support_region_count ?? 0} support regions</small></div>
          <div className="signalCard styleSignal"><i /><span>Style evidence</span><b>{metric(styleEvidenceIndex, 3)}</b><small>{styleDecision?.evidence_tier ?? "unavailable"} · {styleProfile?.creator ?? "no profile"}</small></div>
          <div className="signalCard proofSignal"><i /><span>Evidence receipt</span><b>{proof?.anchor_status ?? "NONE"}</b><small>{chainProof ? "public EAS transaction" : "local transparency receipt"}</small></div>
        </div>
      </details>
    </section>
  );
}
