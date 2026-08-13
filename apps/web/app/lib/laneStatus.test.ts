/**
 * The lane module decides what the product asserts on screen, so the cases that
 * matter here are the ones where a wrong answer is a false claim rather than a
 * cosmetic slip: reporting a match on a clean scan, reporting a clean result
 * when a lane never ran, or describing an undetermined origin as a signal that
 * cleared a threshold.
 *
 * Run with `npm test` (Node strips the types; no test framework is installed).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { findingsLine, laneStatuses, laneStatusList } from "./laneStatus.ts";

type Json = Record<string, unknown>;

/** A scan shaped like the API's, with only the fields under test overridden. */
function scan(overrides: { scan?: Json; packet?: Json } = {}): Json {
  return {
    match_status: "NO_MATCH_IN_CHECKED_SOURCES",
    intended_use: "marketing/social",
    rights_path: "NO_LICENSE_INFO",
    ...overrides.scan,
    evidence_packet: {
      scope: { coverage_status: "COMPLETE" },
      matches: [],
      decision: { match_status: "NO_MATCH_IN_CHECKED_SOURCES" },
      ...overrides.packet,
    },
  };
}

test("a clean scan does not claim a stored-work match", () => {
  const copy = laneStatuses(scan()).copy;
  assert.equal(copy.state, "clear");
  assert.match(copy.headline, /No verified same-work copy/);
});

test("the enum value the API actually emits is read as no match", () => {
  // Regression: an earlier version compared against "NO_MATCH", which the API
  // never emits, so every scan fell through to the match branch.
  for (const status of ["NO_MATCH_IN_CHECKED_SOURCES", "no_match_in_checked_sources"]) {
    assert.equal(laneStatuses(scan({ scan: { match_status: status } })).copy.state, "clear");
  }
});

test("a byte-identical copy is named and attributed", () => {
  const copy = laneStatuses(
    scan({
      scan: { match_status: "MATCH_FOUND" },
      packet: {
        matches: [{ exact_sha256: true, title: "Harbour study", claimant: "A. Maker" }],
        decision: { match_status: "MATCH_FOUND" },
      },
    }),
  ).copy;
  assert.equal(copy.state, "hit");
  assert.match(copy.headline, /Exact reuse of Harbour study/);
  assert.match(copy.answer, /A\. Maker/);
});

test("an inconclusive comparison is review, never a clean result", () => {
  const copy = laneStatuses(scan({ scan: { match_status: "INCONCLUSIVE" } })).copy;
  assert.equal(copy.state, "review");
});

test("an incomplete scope is unchecked, never a clean result", () => {
  for (const status of ["SCOPE_INCOMPLETE", "ERROR"]) {
    const copy = laneStatuses(scan({ scan: { match_status: status } })).copy;
    assert.equal(copy.state, "unchecked", `${status} must not read as clear`);
  }
});

test("an empty catalog is unchecked rather than a pass", () => {
  const copy = laneStatuses(scan({ packet: { scope: { coverage_status: "EMPTY_SCOPE" } } })).copy;
  assert.equal(copy.state, "unchecked");
});

test("an undetermined origin is not described as a signal reaching a threshold", () => {
  // review_recommended is also set when every check was inconclusive, so the
  // engine's own verdict has to win over it.
  const origin = laneStatuses(
    scan({
      packet: {
        synthetic_origin: {
          review_recommended: true,
          presentation: { state: "ORIGIN_UNKNOWN", headline: "Cannot determine origin" },
        },
      },
    }),
  ).origin;
  assert.equal(origin.state, "unchecked");
  assert.doesNotMatch(origin.answer, /threshold/);
  assert.equal(origin.headline, "Cannot determine origin");
});

test("a single AI indicator stays in review rather than becoming a finding", () => {
  // A visible label can be genuine, copied or forged. The engine grades it
  // "review", and the summary must not promote that to a confirmed finding.
  const origin = laneStatuses(
    scan({
      packet: {
        synthetic_origin: {
          classification: "AI_ORIGIN_MARKER_FOUND",
          presentation: { state: "AI_INDICATORS_NEED_REVIEW", headline: "A visible AI label was found" },
        },
      },
    }),
  ).origin;
  assert.equal(origin.state, "review");
  assert.equal(origin.headline, "A visible AI label was found");
  assert.doesNotMatch(origin.answer, /^Yes/);
});

test("trusted provenance asserting AI use is a finding", () => {
  const origin = laneStatuses(
    scan({ packet: { synthetic_origin: { presentation: { state: "AI_CONFIRMED" } } } }),
  ).origin;
  assert.equal(origin.state, "hit");
});

test("a corroborated AI finding is a hit and a quiet one is clear", () => {
  const hit = laneStatuses(
    scan({ packet: { synthetic_origin: { presentation: { state: "AI_INDICATORS_FOUND" } } } }),
  ).origin;
  assert.equal(hit.state, "hit");

  const clear = laneStatuses(
    scan({ packet: { synthetic_origin: { presentation: { state: "NO_STRONG_AI_SIGNAL" } } } }),
  ).origin;
  assert.equal(clear.state, "clear");
});

test("an origin lane that never ran is unchecked", () => {
  assert.equal(laneStatuses(scan()).origin.state, "unchecked");
  const disabled = laneStatuses(
    scan({ packet: { synthetic_origin: { classification: "AI_ORIGIN_CHECK_DISABLED" } } }),
  ).origin;
  assert.equal(disabled.state, "unchecked");
});

test("creator-profile resemblance stays advisory and never becomes a finding", () => {
  const profile = laneStatuses(
    scan({
      packet: {
        style_analysis: {
          decision: { evidence_tier: "VERY_HIGH" },
          top_profiles: [{ creator: "A. Maker" }],
        },
      },
    }),
  ).profile;
  assert.equal(profile.state, "advisory");
  assert.match(profile.headline, /A\. Maker/);
});

test("a profile lane with no registered profile asks for one instead of passing", () => {
  assert.equal(laneStatuses(scan()).profile.state, "unchecked");
});

test("the rights lane reflects the recorded path and the intended use", () => {
  const licensed = laneStatuses(
    scan({ scan: { rights_path: "EXISTING_LICENSE", intended_use: "editorial" } }),
  ).rights;
  assert.equal(licensed.state, "clear");
  assert.match(licensed.answer, /editorial/);

  assert.equal(laneStatuses(scan()).rights.state, "advisory");
});

test("the summary line names only lanes that actually returned something", () => {
  const quiet = scan({
    packet: { synthetic_origin: { presentation: { state: "ORIGIN_UNKNOWN" } } },
  });
  // An origin lane the engine could not determine is not a finding, however the
  // engine's own joint headline phrases it.
  assert.equal(findingsLine(laneStatusList(quiet)), null);

  const matched = scan({
    scan: { match_status: "MATCH_FOUND" },
    packet: {
      decision: { match_status: "MATCH_FOUND" },
      matches: [{ work_title: "Harbour study", geometry: { validated: true } }],
    },
  });
  assert.equal(findingsLine(laneStatusList(matched)), "Stored-work copy found evidence");
});

test("no lane the summary names may contradict its own card", () => {
  const cases = [
    scan(),
    scan({ packet: { synthetic_origin: { presentation: { state: "AI_INDICATORS_FOUND" } } } }),
    scan({ scan: { match_status: "INCONCLUSIVE" }, packet: { decision: { match_status: "INCONCLUSIVE" } } }),
  ];
  for (const candidate of cases) {
    const lanes = laneStatusList(candidate);
    const line = findingsLine(lanes);
    const named = lanes.filter((lane) => lane.state === "hit" || lane.state === "review");
    assert.equal(line === null, named.length === 0);
    for (const lane of lanes) {
      if (lane.state === "unchecked" || lane.state === "clear") {
        assert.ok(!line?.includes(`${lane.key === "copy" ? "stored-work copy" : lane.key} found`));
      }
    }
  }
});
