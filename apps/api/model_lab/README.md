# CreatorProof Model Lab

This directory is the file-backed control plane for Part 1 intelligence. It tracks
identity and qualification; it does not contain model weights, private media, or
benchmark assets.

## What is authoritative

- bundles contains immutable ModelBundle declarations.
- cards describes each provider's purpose, identity boundary, evidence grade, and
  prohibited claims.
- profiles contains versioned creator-profile enrollment and consent declarations.
- registries contains terms, calibration, drift-baseline, detector-lineage, and
  promotion records.
- policies contains preregistered, versioned acceptance gates. The checked-in policy
  is a proposal and cannot authorize promotion until it is ratified before final-test
  access.
- schemas contains machine-readable metadata contracts.

Runtime model bytes remain under models and are ignored by Git. Authorized corpus
media remains outside Git and is referenced by SHA-256 from benchmark manifests.

## Qualification ladder

| State | Meaning |
| --- | --- |
| SOURCE_VERIFIED | Source and intended role are identified; runtime/model claims are not ready. |
| RUNTIME_READY | Exact required artifact bytes, application source, Python/package environment, requirement declarations, and runtime lock are verified locally. |
| SMOKE_TEST_ONLY | The path executes on small fixtures; this is not accuracy validation. |
| DEMO_READY | Terms, fixtures, failure behavior, and rehearsal gates pass for the declared demo. |
| CALIBRATED_DOMAIN_READY | Held-out, leakage-controlled evidence supports a named domain and operating point. |
| PRODUCTION_READY | Operational, legal, security, monitoring, and customer validation gates also pass. |

States are cumulative. A component cannot skip a lower gate, and the bundle cannot
outrank any component required for the demo.

## Safe workflow

1. Validate the source declaration:

       python -m scripts.validate_model_bundle

2. Run the no-media preflight:

       python -m scripts.preflight_part1

3. Fetch an optional artifact with a pinned revision where supported, an expected
   SHA-256 when known, and a metadata output path. The fetch scripts reject a supplied
   digest mismatch before representing the artifact as verified.

4. Never edit a promoted bundle in place. Copy it to a new immutable bundle ID,
   record exact artifact hashes and resolved upstream revisions, then rerun validation.

5. Run smoke checks only against that bundle. Run benchmarks only from authorized,
   lineage-controlled manifests and retain their run-identity, metric-input,
   prediction-row, and full-report digests.

6. Evaluate a sealed report against a policy with
   `python -m scripts.evaluate_model_acceptance REPORT --policy POLICY`. The command
   can recommend a human review; it cannot promote a model.

7. Promotion is a human-reviewed record binding both report and acceptance-policy
   digests. Passing tests or sample-size gates never promotes a model automatically.

## Fail-visible behavior

Missing files, wrong hashes, invalid calibration, absent binaries, and unsupported
devices appear as unavailable, failed, degraded, or scope-incomplete states. They must
never be translated into no copy, human origin, known creator, or permission.

## Current state

The checked-in bundle is RUNTIME_READY. The selected SSCD, Community Forensics, and
CSD bytes are digest-bound and deterministic local probes pass; required copy
components, runtime lock, source-tree revision, exact Python/package versions, and
requirement-file digests are validated by preflight.
The v0.10.0 system also binds embedding caches to model/source/preprocessing identity,
uses regional SSCD nomination, region-aware aligned scoring, selected-profile
multiplicity correction, sealed benchmark reports, runtime telemetry, and explicit
drift-trigger evaluation. Sightengine's `genai` API can be configured as the primary
AI-origin signal with one original-media upload; its remote identity, uncalibrated
semantics, operational fallback, and terms state are recorded separately from locally
pinned model artifacts.
Artifact/data terms, lawful held-out evaluation, consent-backed demo profiles, and
rehearsal remain unresolved. It is therefore not DEMO_READY and must not be advertised
as calibrated or production-ready.
