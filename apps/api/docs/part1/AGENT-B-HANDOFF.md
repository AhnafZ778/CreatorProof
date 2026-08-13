# Part 1 to Part 2 handoff

## Release identity

- Bundle ID: creatorproof-runtime-ready-evidence-v1
- Bundle qualification: RUNTIME_READY
- Application release: 0.10.0 / MODEL-ACCURACY-HARDENING-2026.08.10
- Canonical bundle manifest digest SHA-256: f2a868c47a36f04db9ee79c20b671b29b2ab993c2af4d8bd9bc75d2fe442fdd9
- Runtime source revision:
  creatorproof-source-tree-sha256:2fc65af73f1e19a3d07514c53c0b2890b88876c9f0b9ba7b83ca61e29a446378
- Runtime lock SHA-256: cf946c3c544ea63e9eb0eca739973754dabeca5c3343b0cffaaffa36c0b9f4e7
- Evidence contract: backward-compatible creatorproof.evidence_packet.v1
- Policy: creatorproof-demo-policy-v1
- Demo readiness: false

RUNTIME_READY means exact required bytes, runtime lock, application source,
Python/package versions, requirement-file declarations, and local deterministic probes
are verified. It does not mean benchmarked, calibrated,
terms-approved, legally approved, DEMO_READY, or production-ready.

## Stable implementation outputs

- Health and Evidence Packets expose bundle identity and effective runtime-validation
  state.
- Scope records eligible, nominated, verified, omitted, and failed catalog entries.
- Demo-sized catalogs are exhaustively verified within a configurable bound.
- Benchmark metrics bind benchmark input, validated corpus manifests, bundle, policy,
  and prediction rows by digest. Legacy unbound inputs are smoke-only.
- C2PA exposes manifest, signature, signer trust, AI assertion, ingredient, and trust
  policy separately.
- Passive origin calibration is invalidated by provider/model/artifact/preprocessing/
  domain/crop drift.
- Sightengine is the primary AI-origin route when server-side credentials are present.
  A successful result is not blended with local models; explicit operational failure
  activates the local fallback and is recorded.
- Creator profiles are versioned and consent-backed. Claimant grouping cannot escalate.
- Every policy output has versioned inputs and a deterministic replay-trace digest.
- SSCD candidate nomination records whole-image versus regional scores and the selected
  query view. Regional nomination cannot change final copy semantics by itself.
- Aligned structure records whether the full validated overlap or geometry-verified
  support regions were evaluated.
- Runtime telemetry records bounded stage/cache/score summaries without storing media.

## Selected external runtime identities

| Component | Identity | State |
| --- | --- | --- |
| SSCD | SHA-256 9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56 | deterministic CPU probe passed |
| Community Forensics | HF 6076002bf0d9dd37537f965ee2f06f826c333b61; SHA-256 b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387 | deterministic CPU probe passed; uncalibrated |
| Sightengine genai | vendor-managed API; `SIGHTENGINE_GENAI_ORIGINAL_MEDIA_UPLOAD_V1` | SOURCE_VERIFIED remote primary; uncalibrated and not byte-pinned |
| CSD ViT-L | source 3a9df32605b869eceb704897839be80977a9f1ea; HF 5bc26a6fb0487f3f00a2a7313135103a005b1b67; SHA-256 40e92fad63a361b8136100cd234c42d401ef9b34ff1748234318929ebcc7e7a1 | deterministic CPU probe passed; experimental |
| c2patool | operator binary 0.27.7 observed | component remains SOURCE_VERIFIED pending enforced binary/trust identity |
| Tesseract | operator binary 5.3.4 observed | component remains SOURCE_VERIFIED pending language-data identity |

## Stable fixtures

Use tests/fixtures/part1/packet-scenarios.v1.json. It contains ten expected packet
fragments for exact allowed use, transformed reuse, hard negative, complete no-match,
degraded retrieval, trusted AI provenance, unresolved origin, forgeable marker,
profile resemblance without copy, and disputed rights.

Use tests/fixtures/part1/policy-cases.v1.json for deterministic policy routing. These
fixtures do not authorize public use of any media.

## Added packet fields Part 2 should render

- model_bundle manifest, component, runtime-validation, and promotion state;
- provenance trust_details;
- style profile ID/version/source/consent/authorization and profile manifest status;
- detector artifact and preprocessing identity plus calibration context;
- AI-origin `provider_role`, `provider_details`, original/delivery/spatial scores,
  aggregation strategy, transformation state, `forensic_indicators`, and runtime routing;
- decision.policy_trace with trace_digest_sha256.
- copy evidence `ai_regional_similarity` and `retrieval_view`;
- aligned-structure `evaluation_mask_policy`, `support_region_count`,
  `support_overlap_ratio`, and `support_fraction_of_aligned_overlap`;
- top-level `runtime_telemetry` stage, counter, and score summaries.

See PART2-EVIDENCE-CONTRACT.md for invariants and compatibility meanings.

## New or important reason codes

- CORPUS_MANIFEST_BINDING_NOT_DECLARED
- PROFILE_CONSENT_NOT_CONFIRMED
- STYLE_POLICY_ESCALATION_SUPPRESSED
- ABSENCE_DOES_NOT_ESTABLISH_HUMAN_ORIGIN
- C2PA_SIGNER_TRUST_NOT_CONFIRMED
- CALIBRATION_CONTEXT_MISMATCH
- SIGHTENGINE_PRIMARY_RESULT_USED
- SIGHTENGINE_PRIMARY_FAILURE_LOCAL_FALLBACK_USED
- TRANSFORM_SENSITIVE_SIGNAL_RETAINS_REVIEW_ONLY

Existing coverage, claim-state, rights, and origin-mode reason codes remain stable.

## Known disabled or blocked capability

- The configured GRIP external command currently names an unavailable outer executable
  called python. The router now excludes it and reports
  EXTERNAL_DETECTOR_EXECUTABLE_NOT_FOUND:python instead of crashing later. Configure
  an explicit executable such as ./.venv/bin/python after verifying that environment.
- No target-domain calibration file is configured.
- Sightengine credentials are not configured in the repository. Service terms,
  privacy/retention review, credential rotation, and live authorized-media validation
  remain operator gates.
- No creator is enrolled by default.
- The required SSCD terms record remains REVIEW_REQUIRED.
- No authorized final demo/test corpus or empirical report is checked in.
- No customer workflow study or final-machine rehearsal is claimed.

## Required Part 2 actions

1. Render unavailable/degraded states and all scope counts without optimistic copy.
2. Preserve lane independence and the policy/proof boundaries.
3. Develop against fixtures rather than optional live models.
4. Represent local Merkle and mined EAS receipts distinctly.
5. Add persistence/versioning for normalized rights assertions, profile withdrawal,
   reviewer override, dispute history, and future policy dry runs.
6. Hold a compatibility review before any enum or field rename.
