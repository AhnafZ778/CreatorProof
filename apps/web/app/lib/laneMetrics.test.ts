/**
 * A gauge is read before the sentence beside it, so the failure that matters
 * here is a ring that draws a number the scan never produced — a zero standing
 * in for a lane that did not run, or a donut whose arcs do not add up to the
 * catalog it claims to describe.
 *
 * Run with `npm test` (Node strips the types; no test framework is installed).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  coverageBreakdown,
  laneMetrics,
  originEvidenceQuality,
  usableMetric,
} from "./laneMetrics.ts";

type Json = Record<string, unknown>;

function scan(packet: Json = {}): Json {
  return { evidence_packet: { scope: {}, matches: [], ...packet } };
}

test("a lane that produced no number is empty rather than zero", () => {
  const metrics = laneMetrics(scan());
  for (const key of ["copy", "origin", "profile"] as const) {
    assert.equal(metrics[key].value, null, `${key} invented a value`);
    assert.equal(metrics[key].display, "—");
  }
});

test("the copy ring prefers the fused evidence index", () => {
  const copy = laneMetrics(
    scan({ matches: [{ fusion: { evidence_index: 0.824 }, prototype_evidence_score: 0.2 }] }),
  ).copy;
  assert.equal(copy.value, 0.824);
  assert.equal(copy.display, "0.82");
});

test("a byte-identical file reads as a full copy lane even without a fusion score", () => {
  const copy = laneMetrics(scan({ matches: [{ exact_sha256: true }] })).copy;
  assert.equal(copy.value, 1);
  assert.equal(copy.display, "1.00");
});

test("the origin ring normalises the 0-100 scorecard onto the gauge", () => {
  const origin = laneMetrics(
    scan({ synthetic_origin: { scorecard: { signal_score: 71 } } }),
  ).origin;
  assert.equal(origin.value, 0.71);
  assert.equal(origin.display, "71");
});

test("the origin ring falls back to the fused detector score on its own scale", () => {
  const origin = laneMetrics(scan({ synthetic_origin: { fused_detector_score: 0.42 } })).origin;
  assert.equal(origin.value, 0.42);
  assert.equal(origin.display, "42");
});

test("evidence quality is reported separately from signal strength", () => {
  const packet = scan({
    synthetic_origin: { scorecard: { signal_score: 88, evidence_quality_score: 20 } },
  });
  assert.equal(laneMetrics(packet).origin.display, "88");
  assert.equal(originEvidenceQuality(packet).display, "20");
});

test("a score the engine calls uncalibrated says so", () => {
  // The case that produced this rule: a style index of 0.88 rendered beside
  // "no resemblance above threshold", because the catalog held one exemplar
  // and no threshold had been established for it.
  const profile = laneMetrics(
    scan({
      style_analysis: {
        decision: {
          evidence_index: 0.878,
          calibration_state: "INSUFFICIENT_EMPIRICAL_SUPPORT",
          score_semantics: "UNCALIBRATED_CORROBORATED_STYLE_EVIDENCE_INDEX_NOT_PROBABILITY",
        },
      },
    }),
  ).profile;
  assert.equal(profile.display, "0.88");
  assert.match(profile.qualifier ?? "", /uncalibrated/i);
});

test("a calibrated score carries no calibration warning", () => {
  const profile = laneMetrics(
    scan({ style_analysis: { decision: { evidence_index: 0.4, calibration_state: "READY" } } }),
  ).profile;
  assert.equal(profile.qualifier, null);
});

test("the AI signal score is never presented as a probability", () => {
  const origin = laneMetrics(
    scan({
      synthetic_origin: {
        scorecard: {
          signal_score: 61,
          score_semantics: "SIGNAL_STRENGTH_AND_EVIDENCE_QUALITY_NOT_AI_PROBABILITY",
        },
      },
    }),
  ).origin;
  assert.match(origin.qualifier ?? "", /not a probability/i);
});

test("the rights lane never carries a score", () => {
  const rights = laneMetrics(scan({ decision: { rights_path: "EXISTING_LICENSE" } })).rights;
  assert.equal(rights.value, null);
});

test("a non-finite score is treated as missing, not as a value", () => {
  const copy = laneMetrics(scan({ matches: [{ copy_evidence_score: Number.NaN }] })).copy;
  assert.equal(copy.value, null);
});

test("an undetermined origin lane withholds its zero instead of drawing it", () => {
  // The engine reports signal_score 0 when its checks were inconclusive. Drawn
  // as a gauge that reads "0 AI signal", which is the opposite of undetermined.
  const raw = laneMetrics(
    scan({ synthetic_origin: { scorecard: { signal_score: 0 }, fused_detector_score: 0.001 } }),
  ).origin;
  assert.equal(raw.value, 0);

  const shown = usableMetric(raw, "unchecked");
  assert.equal(shown.value, null);
  assert.equal(shown.display, "—");
});

test("a lane that did reach a conclusion keeps its zero", () => {
  const raw = laneMetrics(scan({ synthetic_origin: { scorecard: { signal_score: 0 } } })).origin;
  assert.equal(usableMetric(raw, "clear").value, 0);
  assert.equal(usableMetric(raw, "clear").display, "0");
});

test("an uncalibrated index behind a clean answer moves out of the gauge", () => {
  // The style lane gates its tiers on calibration and independent support, so a
  // raw 0.91 can sit behind "no resemblance above threshold". Drawn as a large
  // ring it argues against the sentence beside it.
  const raw = laneMetrics(
    scan({
      style_analysis: {
        decision: { evidence_index: 0.91, calibration_state: "NOT_READY" },
      },
    }),
  ).profile;
  assert.equal(raw.value, 0.91);

  const shown = usableMetric(raw, "clear");
  assert.equal(shown.value, null, "the ring still asserts a resemblance");
  assert.match(shown.withheld ?? "", /0\.91/, "the number was dropped rather than relocated");
  assert.match(shown.withheld ?? "", /uncalibrated/);
});

test("an uncalibrated index behind an actual finding is still shown", () => {
  const raw = laneMetrics(
    scan({
      style_analysis: {
        decision: { evidence_index: 0.91, calibration_state: "NOT_READY" },
      },
    }),
  ).profile;
  for (const state of ["hit", "review"] as const) {
    assert.equal(usableMetric(raw, state).value, 0.91);
    assert.equal(usableMetric(raw, state).withheld, null);
  }
});

test("the coverage arcs account for every eligible reference", () => {
  const breakdown = coverageBreakdown(
    scan({
      scope: {
        eligible_reference_count: 40,
        verified_candidate_count: 6,
        omitted_candidate_count: 2,
        failed_candidate_count: 1,
      },
    }),
  );
  assert.equal(breakdown.screenedOut, 31);
  assert.equal(
    breakdown.verified + breakdown.omitted + breakdown.failed + breakdown.screenedOut,
    breakdown.eligible,
  );
  assert.equal(breakdown.total, 40);
});

test("an empty catalog reports nothing searched rather than a full ring", () => {
  const breakdown = coverageBreakdown(scan({ scope: { eligible_reference_count: 0 } }));
  assert.equal(breakdown.known, true);
  assert.equal(breakdown.total, 0);
  assert.equal(breakdown.screenedOut, 0);
});

test("a packet with no scope block is unknown rather than empty", () => {
  assert.equal(coverageBreakdown({ evidence_packet: {} }).known, false);
  assert.equal(coverageBreakdown({}).known, false);
});

test("counts that exceed the eligible total still draw a whole circle", () => {
  // Defensive: a malformed packet must not render arcs that overflow the ring.
  const breakdown = coverageBreakdown(
    scan({
      scope: {
        eligible_reference_count: 2,
        verified_candidate_count: 3,
        omitted_candidate_count: 1,
      },
    }),
  );
  assert.equal(breakdown.screenedOut, 0);
  assert.equal(breakdown.total, 4);
});
