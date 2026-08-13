/**
 * The numbers behind the lane answers.
 *
 * `laneStatus.ts` decides what each lane *says*; this decides what each lane
 * *scores*, and the split is deliberate. A gauge is read faster than a
 * sentence, so it is the more dangerous of the two: a ring drawn at zero and a
 * ring drawn from a lane that never ran look identical unless the difference is
 * made explicit. Every function here returns `null` for "no number" and never
 * substitutes a zero, and `coverageBreakdown` reports `known: false` rather
 * than an empty circle when the scope counts are missing.
 */

import type { LaneKey, LaneState } from "./laneStatus";

type Record_ = Record<string, unknown>;

function asRecord(value: unknown): Record_ | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record_) : null;
}

function asArray(value: unknown): Record_[] {
  return Array.isArray(value) ? (value.filter((item) => asRecord(item)) as Record_[]) : [];
}

/** Finite numbers only: NaN and Infinity are missing data wearing a number's clothes. */
function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function count(value: unknown): number {
  const parsed = num(value);
  return parsed === null ? 0 : Math.max(0, Math.round(parsed));
}

export type LaneMetric = {
  key: LaneKey;
  /** 0..1 for the gauge, or null when this lane produced no measurement. */
  value: number | null;
  /** What is printed inside the ring. */
  display: string;
  /** What the number means, in words. */
  caption: string;
  /** How the number must be read, when the engine says its scale is limited. */
  qualifier: string | null;
  /**
   * Set when a real number was measured but withheld from the gauge, carrying
   * the reason it cannot be shown as the lane's answer. See `usableMetric`.
   */
  withheld: string | null;
};

/**
 * The engine labels the standing of its own scores, and those labels are
 * load-bearing rather than decorative. A style index of 0.88 printed beside
 * "no resemblance above threshold" is a flat contradiction until the reader is
 * told the index was never calibrated against this catalog; an AI signal score
 * is not a probability and stops being honest the moment it is read as one.
 * Where the packet states how a number should be read, that qualification
 * travels with the number rather than being dropped at the UI boundary.
 */
function qualifier(semantics: unknown, calibrationState: unknown): string | null {
  const calibration = typeof calibrationState === "string" ? calibrationState.toUpperCase() : "";
  if (calibration && calibration !== "READY" && calibration !== "CALIBRATED") {
    return "uncalibrated for this catalog";
  }
  const label = typeof semantics === "string" ? semantics.toUpperCase() : "";
  // The engine spells this several ways — `NOT_PROBABILITY` on the copy and
  // style indices, `NOT_AI_PROBABILITY` on the origin scorecard.
  if (/NOT_[A-Z_]*PROBABILITY/.test(label)) return "a strength score, not a probability";
  if (label.startsWith("UNCALIBRATED")) return "uncalibrated for this catalog";
  return null;
}

export type CoverageBreakdown = {
  /** False when the packet carried no scope counts at all. */
  known: boolean;
  /** Every eligible reference in the declared catalog. */
  eligible: number;
  verified: number;
  omitted: number;
  failed: number;
  /** Eligible references retrieval ruled out before verification ran. */
  screenedOut: number;
  /** The three accounted-for buckets plus `screenedOut`, which is what the donut draws. */
  total: number;
};

/**
 * Split the eligible catalog into what actually happened to each reference.
 *
 * The buckets are made to sum to the eligible count so the donut is a true
 * part-to-whole: anything not verified, omitted or failed was ruled out by
 * retrieval, and saying so is more honest than leaving an unexplained arc.
 */
export function coverageBreakdown(scan: Record_): CoverageBreakdown {
  const scope = asRecord(asRecord(scan.evidence_packet)?.scope);
  if (!scope) {
    return { known: false, eligible: 0, verified: 0, omitted: 0, failed: 0, screenedOut: 0, total: 0 };
  }

  const eligible = count(scope.eligible_reference_count);
  const verified = count(scope.verified_candidate_count);
  const omitted = count(scope.omitted_candidate_count);
  const failed = count(scope.failed_candidate_count);
  const accounted = verified + omitted + failed;
  const screenedOut = Math.max(0, eligible - accounted);

  return {
    known: true,
    eligible,
    verified,
    omitted,
    failed,
    screenedOut,
    // Falls back to the accounted buckets if they exceed the eligible count, so
    // a malformed packet still draws proportions that add up to what is shown.
    total: Math.max(eligible, accounted),
  };
}

function metric(
  key: LaneKey,
  caption: string,
  value: number | null,
  display: string,
  note: string | null = null,
): LaneMetric {
  return { key, value, display, caption, qualifier: value === null ? null : note, withheld: null };
}

/** No measurement was made, as distinct from a measurement that came back low. */
function unmeasured(key: LaneKey, caption: string): LaneMetric {
  return metric(key, caption, null, "—");
}

function copyMetric(packet: Record_ | null): LaneMetric {
  const caption = "Copy evidence index";
  const top = asArray(packet?.matches)[0] ?? null;
  const fusion = asRecord(top?.fusion);
  const note = qualifier(fusion?.score_semantics, null);

  // A byte-identical file is the ceiling of this lane whether or not the
  // fusion stage bothered to score it.
  if (top?.exact_sha256 === true) return metric("copy", caption, 1, "1.00", note);

  const value =
    num(top?.copy_evidence_score) ??
    num(fusion?.evidence_index) ??
    num(top?.prototype_evidence_score);

  return value === null
    ? unmeasured("copy", caption)
    : metric("copy", caption, value, value.toFixed(2), note);
}

function originMetric(packet: Record_ | null): LaneMetric {
  const caption = "AI signal score";
  const synthetic = asRecord(packet?.synthetic_origin);
  const scorecard = asRecord(synthetic?.scorecard);
  const note = qualifier(scorecard?.score_semantics, null);

  const scored = num(scorecard?.signal_score);
  if (scored !== null) {
    return metric("origin", caption, scored / 100, String(Math.round(scored)), note);
  }

  const fused = num(synthetic?.fused_detector_score);
  if (fused !== null) {
    return metric("origin", caption, fused, String(Math.round(fused * 100)), note);
  }

  return unmeasured("origin", caption);
}

/** The confidence qualifier on the origin score, which is a separate quantity. */
export function originEvidenceQuality(scan: Record_): LaneMetric {
  const caption = "Evidence quality";
  const scorecard = asRecord(
    asRecord(asRecord(scan.evidence_packet)?.synthetic_origin)?.scorecard,
  );
  const quality = num(scorecard?.evidence_quality_score);
  return quality === null
    ? unmeasured("origin", caption)
    : metric("origin", caption, quality / 100, String(Math.round(quality)));
}

function profileMetric(packet: Record_ | null): LaneMetric {
  const caption = "Creator-profile index";
  const decision = asRecord(asRecord(packet?.style_analysis)?.decision);
  const value = num(decision?.evidence_index);
  const note = qualifier(decision?.score_semantics, decision?.calibration_state);
  return value === null
    ? unmeasured("profile", caption)
    : metric("profile", caption, value, value.toFixed(2), note);
}

/**
 * The rights lane is a record, not a measurement. It is represented here so
 * callers can iterate all four lanes uniformly, but it never carries a score.
 */
function rightsMetric(): LaneMetric {
  return unmeasured("rights", "Recorded rights, not a score");
}

/**
 * Withhold a score the gauge would state more strongly than the evidence does.
 *
 * Two cases, both of which put a number on screen that argues against the
 * sentence beside it:
 *
 * A lane that never reached a conclusion still reports a number. The origin
 * lane returns `signal_score: 0` when its checks are inconclusive, and a gauge
 * at zero beside "the origin could not be established" reads as *confirmed not
 * AI* — the inversion of what the scan found. Zero is a measurement; a lane
 * that did not run never made one.
 *
 * A lane that found nothing can still hold a high raw index. The style lane
 * gates its tiers on calibration and independent support, so an uncalibrated
 * 0.91 sits behind "no resemblance above threshold" — a number the engine
 * itself declined to treat as evidence. A qualifying caption does not undo a
 * large amber ring, so the number moves into the caption instead of leading.
 */
export function usableMetric(metric: LaneMetric, state: LaneState): LaneMetric {
  const blank = { ...metric, value: null, display: "—", qualifier: null };
  if (state === "unchecked") return { ...blank, withheld: null };
  if (metric.value !== null && metric.qualifier === "uncalibrated for this catalog") {
    if (state === "clear" || state === "advisory") {
      return { ...blank, withheld: `raw index ${metric.display}, ${metric.qualifier}` };
    }
  }
  return metric;
}

export function laneMetrics(scan: Record_): Record<LaneKey, LaneMetric> {
  const packet = asRecord(scan.evidence_packet);
  return {
    copy: copyMetric(packet),
    origin: originMetric(packet),
    profile: profileMetric(packet),
    rights: rightsMetric(),
  };
}
