"use client";

/**
 * The first thing anyone reads after a scan.
 *
 * Order is a product rule, not a layout preference: coverage is placed beside
 * the outcome, on the side the eye reaches first, because a confident-looking
 * decision taken over an incomplete search is the one failure mode this product
 * cannot afford. Each lane then answers its own question separately, so a copy
 * match is never read as an AI-origin finding.
 *
 * Colour follows the same rule the tokens set: a lane hue is an identity, never
 * a verdict. The rings are therefore drawn in their lane's colour whatever they
 * found, and the finding itself is stated in words on a chip beside them.
 */

import {
  coverageBreakdown,
  laneMetrics,
  originEvidenceQuality,
  usableMetric,
  type LaneMetric,
} from "@/app/lib/laneMetrics";
import {
  findingsLine,
  laneStatusList,
  type LaneKey,
  type LaneState,
  type LaneStatus,
} from "@/app/lib/laneStatus";
import { isPublicBlockchainProof } from "@/app/lib/verifyStatement";

import { CoverageDonut, MetricBar, ScoreRing, type DonutSegment } from "./EvidenceCharts";

type Record_ = Record<string, unknown>;

function asRecord(value: unknown): Record_ | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record_) : null;
}

function text(value: unknown, fallback = "not reported"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

const COVERAGE_COPY: Record<string, { tone: string; headline: string; detail: string }> = {
  COMPLETE: {
    tone: "ok",
    headline: "The whole catalog was searched",
    detail: "Every eligible reference in this catalog was compared against the candidate.",
  },
  EMPTY_SCOPE: {
    tone: "warn",
    headline: "This catalog is empty",
    detail: "Register protected works in this catalog before a quiet result means anything.",
  },
  PARTIAL: {
    tone: "warn",
    headline: "Part of the catalog was searched",
    detail: "A clean copy result cannot be claimed until the remaining references are checked.",
  },
  DEGRADED: {
    tone: "warn",
    headline: "The search ran without its full stack",
    detail: "Learned descriptors were unavailable for some references in this catalog.",
  },
  TRUNCATED: {
    tone: "warn",
    headline: "The candidate set was cut short",
    detail: "More references matched the shortlist than this run was allowed to verify.",
  },
  FAILED: {
    tone: "bad",
    headline: "The search did not complete",
    detail: "Run the scan again to produce a complete evidence packet.",
  },
};

const DECISION_COPY: Record<string, { label: string; meaning: string; next: string }> = {
  PASS_BY_POLICY: {
    label: "Cleared by your policy",
    meaning: "The recorded rights cover the intended use for the evidence that was found.",
    next: "Publish if your own sign-off process is satisfied, and keep the evidence packet with the asset.",
  },
  REVIEW: {
    label: "Ready for human review",
    meaning:
      "Evidence was found that your policy will not decide on its own. A person has to make the call.",
    next: "Open the evidence workspace below, inspect the matched regions, and record the disposition.",
  },
  BLOCK: {
    label: "Hold before publishing",
    meaning: "Your policy blocks this combination of evidence and intended use.",
    next: "Obtain a licence, change the intended use, or escalate to the rights owner.",
  },
};

/** What each lane found, said plainly enough to be read before the number is.
 *  `unchecked` covers a lane that never ran and a lane that ran without
 *  reaching a usable reading, so it is worded for the outcome rather than the
 *  cause: either way the reader has no answer from this lane. */
const STATE_CHIP: Record<LaneState, string> = {
  hit: "Evidence found",
  review: "Needs review",
  advisory: "Context only",
  clear: "Nothing found",
  unchecked: "No result",
};

const LANE_TAG: Record<LaneKey, string> = {
  copy: "STORED-WORK COPY",
  origin: "AI ORIGIN",
  profile: "CREATOR PROFILE",
  rights: "RECORDED RIGHTS",
};

/** Where a ring is blank or its scale is limited, say so in the caption. */
function ringCaption(lane: LaneStatus, metric: LaneMetric): string {
  if (lane.key === "rights") return metric.caption;
  if (metric.withheld) {
    const said = metric.withheld.charAt(0).toUpperCase() + metric.withheld.slice(1);
    return `${said} — not shown as a score`;
  }
  if (metric.value === null) {
    return lane.state === "unchecked"
      ? "This lane produced no usable score"
      : "No score was returned";
  }
  return metric.qualifier ? `${metric.caption} · ${metric.qualifier}` : metric.caption;
}

export default function ScanVerdict({
  scan,
  onOpenProof,
  onOpenEvidence,
}: {
  scan: Record_;
  onOpenProof?: () => void;
  onOpenEvidence?: () => void;
}) {
  const packet = asRecord(scan.evidence_packet);
  const scope = asRecord(packet?.scope);
  const decision = asRecord(packet?.decision);
  const proof = asRecord(packet?.proof);

  const coverageStatus = text(scope?.coverage_status, "UNKNOWN").toUpperCase();
  const coverage = COVERAGE_COPY[coverageStatus] ?? {
    tone: "warn",
    headline: "Coverage was not reported",
    detail: "Open the evidence workspace to inspect the source record.",
  };
  const policyAction = text(scan.policy_action ?? decision?.policy_action, "REVIEW").toUpperCase();
  const outcome = DECISION_COPY[policyAction] ?? DECISION_COPY.REVIEW;

  const lanes = laneStatusList(scan);
  const metrics = laneMetrics(scan);
  const quality = originEvidenceQuality(scan);
  const breakdown = coverageBreakdown(scan);

  const segments: DonutSegment[] = [
    { key: "verified", label: "verified", value: breakdown.verified, color: "var(--cp-lane-copy)" },
    { key: "screened", label: "ruled out by retrieval", value: breakdown.screenedOut, color: "rgba(255,255,255,0.34)" },
    { key: "omitted", label: "omitted", value: breakdown.omitted, color: "var(--cp-review)" },
    { key: "failed", label: "failed", value: breakdown.failed, color: "var(--cp-block)" },
  ];
  const laneFindings = lanes.filter((lane) => lane.state === "hit" || lane.state === "review").length;
  const findings = findingsLine(lanes);

  return (
    <section className={`scanVerdict action-${policyAction.toLowerCase()}`} id="bottom-line" aria-label="Scan result">
      <div className="verdictHero">
        <div className={`verdictCoverage tone-${coverage.tone}`}>
          <small>COVERAGE FIRST</small>
          <CoverageDonut
            segments={segments}
            centre={breakdown.known ? String(breakdown.total) : "—"}
            centreLabel={breakdown.total === 1 ? "eligible work" : "eligible works"}
          />
          <b>{coverage.headline}</b>
          <p>{coverage.detail}</p>
          <ul className="verdictCoverageKey">
            {segments
              .filter((segment) => segment.value > 0)
              .map((segment) => (
                <li key={segment.key}>
                  <i style={{ background: segment.color }} aria-hidden="true" />
                  <b>{segment.value}</b>
                  <span>{segment.label}</span>
                </li>
              ))}
            {breakdown.total === 0 && <li className="isEmpty">Nothing in this catalog was searchable</li>}
          </ul>
        </div>

        <div className="verdictDecision">
          <div className="verdictStampRow">
            <span className="verdictStamp">{policyAction.replace(/_/g, " ")}</span>
            <span className="verdictFindings">
              {laneFindings === 0
                ? "No lane returned a finding"
                : `${laneFindings} of ${lanes.length} lanes returned something`}
            </span>
          </div>
          <h2>{outcome.label}</h2>
          <p className="verdictMeaning">{outcome.meaning}</p>
          {findings && <p className="verdictJoint">{findings}</p>}

          <div className="verdictNext">
            <small>WHAT TO DO NEXT</small>
            <p>{outcome.next}</p>
            <div className="verdictActions">
              {onOpenEvidence && (
                <button type="button" className="isPrimary" onClick={onOpenEvidence}>
                  Open the evidence
                </button>
              )}
              {onOpenProof && (
                <button type="button" onClick={onOpenProof}>
                  Verify the proof
                </button>
              )}
            </div>
          </div>

          <div className="verdictProofChip">
            <span className="verdictProofDot" aria-hidden="true" />
            <b>
              {isPublicBlockchainProof(proof)
                ? "Public blockchain attestation"
                : "Tamper-evident evidence receipt"}
            </b>
            <span>
              {text(proof?.anchor_status, "UNKNOWN")} · {text(proof?.provider, "unknown provider")}
            </span>
          </div>
        </div>
      </div>

      <div className="verdictLanes">
        {lanes.map((lane) => {
          const metric = usableMetric(metrics[lane.key], lane.state);
          return (
            <article key={lane.key} className={`verdictLane lane-${lane.key} state-${lane.state}`}>
              <header>
                <span className="verdictLaneTag">{LANE_TAG[lane.key]}</span>
                <span className="verdictLaneChip">{STATE_CHIP[lane.state]}</span>
              </header>
              <div className="verdictLaneBody">
                {lane.key === "rights" ? (
                  <div className="verdictLaneGlyph" aria-hidden="true">
                    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M15 3h4a2 2 0 0 1 2 2v4" />
                      <path d="M9 21H5a2 2 0 0 1-2-2v-4" />
                      <path d="M7 8h10" />
                      <path d="M7 12h7" />
                      <path d="M7 16h4" />
                    </svg>
                  </div>
                ) : (
                  <ScoreRing
                    value={metric.value}
                    display={metric.display}
                    caption={metric.caption}
                  />
                )}
                <div className="verdictLaneText">
                  <p className="verdictLaneQuestion">{lane.question}</p>
                  <b>{lane.answer}</b>
                </div>
              </div>
              <footer>
                <span>{ringCaption(lane, metric)}</span>
                {/* Only meaningful next to a signal score it qualifies. */}
                {lane.key === "origin" && metric.value !== null && quality.value !== null && (
                  <MetricBar
                    label="Evidence quality"
                    value={quality.value}
                    display={`${quality.display}/100`}
                  />
                )}
              </footer>
            </article>
          );
        })}
      </div>
    </section>
  );
}
