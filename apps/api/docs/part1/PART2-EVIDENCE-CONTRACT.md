# Part 1 to Part 2 evidence contract

## Compatibility promise

Part 1 preserves Evidence Packet v1 and adds fields backward-compatibly. Part 2 may
render, persist, sign, and anchor these facts but must not reinterpret or overwrite
them.

## Stable enums

- Match: MATCH_FOUND, INCONCLUSIVE, NO_MATCH_IN_CHECKED_SOURCES,
  SCOPE_INCOMPLETE, ERROR.
- Coverage: COMPLETE, EMPTY_SCOPE, PARTIAL, DEGRADED, TRUNCATED, FAILED.
- Capability: NOT_CONFIGURED, READY, EXECUTED, SKIPPED_BY_POLICY, UNAVAILABLE, FAILED.
- Origin policy: DISABLED, INFORMATIONAL, REQUIRED.
- Copy retrieval: BASELINE_ALLOWED, LEARNED_REQUIRED.
- Policy: PASS_BY_POLICY, REVIEW, BLOCK.
- Claim: ASSERTED, CORROBORATED, DISPUTED, SUPERSEDED, REVOKED.

## Fields Part 2 should expose

Model bundle:

- immutable bundle ID, manifest digest, qualification state, runtime lock digest;
- component provider/model/preprocessing/source/artifact/terms states;
- active provider status and unavailable reason.

Scope:

- catalog/version/snapshot digest;
- eligible, nominated, verified, omitted, and failed counts;
- requested and executed retrieval provider;
- capability execution states and coverage reasons.

Provenance and origin:

- manifest, signature, signer trust, AI assertion, and ingredient facts separately;
- visible marker as forgeable;
- detector artifact, preprocessing, calibration, family count, stability, errors,
  abstention, and negative-clearance support.
- primary/fallback provider role and runtime route state;
- allowlisted global/generator-category provider cues, spatial hotspots, and
  transformation resilience, always labelled as model signals rather than provenance
  or pixel-level explanations.

Creator profile:

- profile ID/version/source/consent state and authorization;
- readout/calibration/profile health/content confound;
- review recommendation remains advisory and cannot manufacture copy.

Policy:

- immutable policy inputs and version;
- action, rights path, reason codes;
- deterministic trace and trace digest;
- limitations and missing facts.

Proof:

- packet commitment scope and digest;
- provider and status;
- local receipt versus mined public-chain receipt represented distinctly.

## Part 2 invariants

1. Do not show a no-match pass when coverage is not COMPLETE.
2. Do not label absent provenance or quiet detectors as human.
3. Do not render unvalidated geometry annotations.
4. Do not turn a style profile into copy, identity, authorship, ownership, or block.
5. Do not imply asserted/disputed/revoked claims authorize use.
6. Do not call local Merkle proof blockchain.
7. Do not hide unavailable or failed components.
8. Do not recalculate historical evidence under a new policy silently.

## Stable fixtures

Part 2 should develop against tests/fixtures/part1/packet-scenarios.v1.json rather than
calling optional models during UI work. Any field rename or enum change requires a
compatibility test and an explicit contract review.
