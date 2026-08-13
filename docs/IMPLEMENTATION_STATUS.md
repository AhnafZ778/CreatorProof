# CreatorProof implementation status

This repository is an executable prototype plus production-shaped provider boundaries. It is not represented as a finished SOTA system until the benchmark and promotion gates below are satisfied.

## Runtime flow

```text
Browser
  -> Next.js server-side proxy
  -> FastAPI
     -> API-key tenant boundary
     -> PostgreSQL/SQLite metadata
     -> local/S3-shaped object-store boundary
     -> JobQueue (inline or Redis)
        -> evidence worker
           -> SHA-256 exact check
           -> official C2PA inspection
           -> transformation-aware AI-origin detector ensemble + abstention
           -> SSCD cosine retrieval (pHash fallback if unavailable)
           -> mutual ORB + USAC/MAGSAC fail-closed verification
           -> alignment-conditioned structural corroboration
           -> independent creator-profile resemblance retrieval
           -> catalog-relative empirical style support
           -> independent copy/style/origin fusion
           -> rights/policy evaluation
           -> Evidence Packet + SHA-256 commitment
           -> local Merkle receipt or optional EAS attestation
```

## Implemented now

| Capability | State | Notes |
| --- | --- | --- |
| Reference registration | WORKING | Image validation, digest/fingerprint, catalog scope, rights metadata |
| Claim-state authorization | WORKING / PROTOTYPE WORKFLOW | Only corroborated claims can authorize recorded use; asserted/disputed/superseded/revoked records route review |
| Exact matching | WORKING | SHA-256 |
| Learned retrieval | WORKING WHEN MODEL INSTALLED | Official SSCD `sscd_disc_mixup` TorchScript; cosine-ranked exhaustive demo catalog; per-scan fallback is reported |
| Cheap fallback retrieval | WORKING | DCT pHash, used only when SSCD cannot run for that comparison |
| Local verification | WORKING CONSERVATIVE BASELINE | Mutual ORB matches + USAC/MAGSAC + inlier/coverage/dispersion/symmetric-error/matrix gates |
| Source coverage contract | WORKING / FAIL-CLOSED | Typed complete/empty/partial/degraded/truncated/failed states, eligible manifest, provider execution, omissions, catalog version and snapshot digest |
| Evidence Microscope | WORKING | Six truthful modes: summary, AI origin, copy regions, aligned structure, creator profile, and profile diagnostics; source coverage is visible before the decision |
| AI-origin evidence | WORKING WHEN MODEL INSTALLED | Community Forensics plus external detector adapters, robustness views, held-out calibration and abstention; explicit disabled/informational/required modes |
| Creator-profile resemblance | WORKING / EXPERIMENTAL | Groups registered works by claimant; CSD+ ranking, content control and catalog-relative empirical support |
| CSD style provider | OPTIONAL / EXPERIMENTAL | External CSD ViT-L adapter; upstream current weight-discrepancy warning; must pass local style benchmark |
| Style diagnostic fallback | WORKING | Palette/tone/edge-direction/texture descriptor + 4x4 cross-content tile map; explicitly non-learned |
| Evidence/policy separation | WORKING | Canonical status enums |
| Evidence Packet | WORKING | Deterministic structure and packet commitment |
| Idempotency | WORKING | Tenant/key uniqueness plus canonical candidate/catalog/use digest; changed payload returns typed `409` |
| Candidate deletion | WORKING | Zero-retention default after processing |
| Job queue | WORKING | Inline for tests; Redis list + worker for Compose |
| PostgreSQL | CONFIGURED | Compose path; SQLite is test/quick-start fallback |
| Next.js console | WORKING | Registration, scan, polling, JSON inspection |
| C2PA | WORKING WHEN C2PATOOL INSTALLED | Official CLI adapter; validity, trust and AI assertion are separate; missing manifest is unknown |
| Local proof | WORKING | Domain-separated Merkle inclusion receipt; explicitly not blockchain |
| EAS/blockchain | IMPLEMENTED / LIVE ACTIVATION REQUIRED | Locked Web3 runtime; direct packet attestations plus durable batched checkpoint jobs; full EAS field/schema/attester/chain binding and transaction reconciliation. Repository contains no signer or deployment-specific schema UID, and a live acceptance transaction is still required |
| SSCD | INTEGRATED / EXPERIMENTAL | Local TorchScript provider and cached descriptors; accuracy/threshold promotion still requires project benchmark |
| OpenRouter explainer | OPTIONAL / WORKING | Server-only API key; explains structured metrics only and never changes detection |
| Learned matcher | PROMOTION GATE | Tournament LightGlue/ALIKED/XFeat/LoMa/RoMa-family candidates |
| pgvector/Qdrant | SCALE GATE | Not necessary for the tiny demo catalog |
| Calibration | PARTIALLY IMPLEMENTED / DOMAIN DATA REQUIRED | AI-origin calibration registry and style cohort empirical support are implemented; neither is presented as universal probability or conformal coverage |

## Required Model Lab gate

No research model should replace the CPU baseline merely because a paper reports better numbers. A candidate must be evaluated on the CreatorProof benchmark using source-original-disjoint train/calibration/test splits.

Minimum report:

- Recall@K and mAP for candidate retrieval.
- Precision/recall at chosen operating points.
- False-positive rate on hard negatives.
- False-block and review rate under the policy layer.
- Calibration error/Brier score if a calibrated probability-like output is exposed.
- Geometry inliers, query/reference coverage, reprojection error, and localization quality.
- p50/p95 latency, peak memory, GPU/CPU requirements, and estimated cost.
- Per-transformation breakdown: resize, crop, recompression, rotation, perspective, overlay, screenshot, partial reuse, collage, background replacement, and permitted generative edits where the dataset license allows.

## Production blockers

Before selling the API, add or complete:

1. A project-specific, generator/source/creator-disjoint benchmark and calibrated abstention thresholds.
2. Calibrate SSCD or replace it with a benchmark-winning retrieval provider, then add ANN storage at scale.
3. Run a creator-profile resemblance tournament (CSD/CSD+ readout, ALADIN, StyleDecoupler when reproducible),
   measure creator discrimination gaps, and calibrate a review operating point on customer data.
4. A benchmark-winning learned/local geometric verifier.
5. A production C2PA trust policy/trust-list and a broader signed fixture corpus.
6. Hashed API keys, key rotation, tenant-scoped authorization, PostgreSQL RLS, audit events, rate limits, and quotas.
7. S3-compatible storage with short-lived candidate objects and deletion verification.
8. Versioned work/claim/license/catalog entities, database migrations, and backup/restore tests.
9. Webhook delivery with signatures, replay protection, and retry semantics.
10. Promote chain custody from an in-process raw EVM key to an external signer,
    add redundant-RPC/finality monitoring, and complete the live testnet/mainnet
    acceptance and revocation drills in `BLOCKCHAIN_IMPLEMENTATION_AND_DEPLOYMENT.md`.
11. Observability, SLOs, load tests, dependency/SBOM scanning, and an incident runbook.
12. Counsel-reviewed claims language, privacy terms, DPA/retention controls, and a third-party license/model/data inventory.

## Demo acceptance cases

1. Exact copy -> `MATCH_FOUND`. For transformed copies, require validated geometry plus aligned
   structure and global/perceptual corroboration; otherwise abstain or report source-scoped no-match.
2. Same visual match but explicitly allowed intended use -> evidence remains `MATCH_FOUND`; policy can be `PASS_BY_POLICY` with `EXISTING_LICENSE` only when the matched claim is `CORROBORATED`.
3. Hard negative -> nearest reference may still be displayed, but geometry must emit no annotations unless it validates; decision remains `NO_MATCH_IN_CHECKED_SOURCES` or `INCONCLUSIVE`, never `COPYRIGHT_CLEAR` or `ORIGINAL`.
4. Different-content/same-creator-profile labelled positive -> the profile may rank #1 even when copy
   geometry correctly rejects; UI must not draw copy lines in style modes.
5. AI-origin positive -> provenance is evaluated first; detector support must survive common
   transformations or abstain. Low score never proves human creation.
6. AI-generated style imitation -> copy can remain negative while calibrated style and AI-origin
   evidence jointly route to review without declaring infringement.
