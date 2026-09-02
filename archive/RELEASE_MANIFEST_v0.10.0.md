# CreatorProof v0.10.0 — release manifest

Build: `0.10.0 / MODEL-ACCURACY-HARDENING-2026.08.10`

## Release boundary

This release improves the evidence/model system around the existing pinned SSCD,
Community Forensics, and CSD artifacts. It does not claim that those neural-network
weights were retrained, that a deployment-domain accuracy target passed, or that the
bundle is demo/production ready.

## Immutable identities

- Bundle: `creatorproof-runtime-ready-evidence-v1`
- Qualification: `RUNTIME_READY`
- Canonical bundle digest:
  `7a330b9b4a3e61d95820dd20c84665fc463e191a0f7d8043b612e0c4f519f15b`
- Literal bundle file SHA-256:
  `a57ea91740a8fffe5ad53a116f14183c96e54b8e69f7eb2f2b4dd14c60265111`
- API source revision:
  `creatorproof-source-tree-sha256:ccf8fe55ab69bd8ea323f0b6234df1e70f82197452e4027d37c95fa65fbb8326`
- `uv.lock` SHA-256:
  `1e1a33b781fb5364d3389574fb5ef5913d0598347409e5051549b5ce890d3560`
- Generated stress-result digest:
  `d3761d025f8afd1bf56d7a663fbb80c9e42a0ed829023b4ec7dedd3f6814355b`
- API image:
  `sha256:6b370dab5b74d2ee03897061b0641fe59fa92078a61b1b822f61501c04927e57`
- Web image:
  `sha256:d1d9bdd5c70f65a1531f5ac7a8a59eb036e1ac4dda76776d293718b6c0f85717`

## Material behavior changes

- whole-image plus five-region SSCD candidate nomination;
- geometry-support-aware aligned NCC/GMS/SSIM verification;
- selected-profile Bonferroni family-wise correction;
- sealed benchmark rows, metric inputs, and reports;
- source-lineage/creator-clustered uncertainty and error galleries;
- preregistered acceptance-policy evaluator with no automatic promotion;
- identity-bound atomic embedding caches;
- structured C2PA and registry-controlled detector-family/calibration authority;
- strict CSD artifact, source checkout, module origin, and state loading;
- durable Redis claim/ack/retry/dead-letter/stale recovery;
- per-scan telemetry and explicit drift triggers;
- v0.10.0 UI fields for regional retrieval and support-mask evidence.

## Verification snapshot

- Ruff formatting: pass
- Ruff lint: pass
- Backend tests: 177 pass
- Frontend typecheck: pass
- Frontend optimized build: pass
- Docker Compose configuration: pass
- API and web image build: pass
- API image import: `CreatorProof API 0.10.0`
- Local selected-model preflight: `DECLARED_STATE_VERIFIED`
- Lightweight API-image ML preflight: expected exit 3, source/lock match, optional ML
  environment and required SSCD bytes absent

## Measured fixed stress result

- Four-source collage source coverage@4: `66.67% → 100.00%`
- Absolute increase: `33.33 percentage points`
- Relative increase: `50.00%`
- Partial-copy structural signal: `0.564872 → 0.983768`
- Naive selected-profile tail value: `0.047619`; corrected value: `0.142857`
- Evaluation grade: `SYNTHETIC_STRESS_ONLY_NOT_REAL_WORLD_ACCURACY`
- Overall real-world accuracy change: not measured

See [MODEL_ACCURACY_IMPLEMENTATION_BEFORE_AFTER.md](../MODEL_ACCURACY_IMPLEMENTATION_BEFORE_AFTER.md)
for the complete before/after and verification procedure.

