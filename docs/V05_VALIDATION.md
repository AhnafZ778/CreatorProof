# CreatorProof v0.5 validation snapshot

Date: 9 August 2026. Build: `0.5.0 / CORROBORATED-EVIDENCE-2026.08.09`.

## Automated gates in this handoff workspace

- `ruff check app tests scripts`: **pass**.
- `ruff format --check app tests scripts`: **pass** after formatting.
- `pytest -q`: **11 / 11 pass**.
- `npm run typecheck`: **pass**.
- `npm run build`: **pass** under Next.js 16.3.0.

The included test suite covers exact-match/policy separation, hard-negative behavior, idempotency, API
authentication, multi-work style evidence, retrieval/media behavior, fail-closed geometry visualization,
the v0.5 aligned structural verifier, and the explicit “SSCD 0.72 must not veto overwhelming corroborated
near-duplicate evidence” regression.

## User-supplied near-duplicate regression

The supplied side-by-side example was evaluated in memory only; the personal image is not copied into the
repository or packaged ZIP. With the v0.5 SIFT-first verifier, the two displayed image regions produced:

- mutual tentative matches: **221**;
- robust inliers: **215**;
- inlier ratio: **0.972851**;
- candidate/reference coverage: **0.673872 / 0.675089**;
- normalized symmetric transfer error: **0.00095886**;
- aligned structure consensus: **0.924796**.

Holding SSCD at the user's reported **0.72** and pHash similarity at **1.0** for the fusion regression,
v0.5 returns:

- evidence index: **0.901427**;
- tier: **VERY_HIGH**;
- classification: **VERIFIED_NEAR_DUPLICATE**;
- `match_supported`: **true**.

The evidence index is deliberately not described as a probability.

## Synthetic transformation stress pass

A separate in-memory CPU fallback stress pass used one structured reference with six transforms:
colour/contrast, perspective, JPEG quality 58, crop-resize, Gaussian blur, and a large opaque overlay.
After the final corroboration-gate tune all **6 / 6** were verified as matches without an SSCD model.
Three independently generated structured cross-image pairs produced **0 / 3** matches. One difficult
negative happened to fit geometry but remained `REVIEW_CANDIDATE` (`q_geo=0.531008`, structure
`0.603573`) rather than crossing a match gate. This small synthetic pass is a regression check, not an
accuracy estimate.

## Model/runtime caveats in this workspace

The SSCD checkpoint itself is intentionally not bundled in this source handoff. `scripts.check_ai` therefore
reports `SSCD_MODEL_MISSING` here. The supplied fetch/check scripts and master execution prompt install and
verify it on the user's machine. Do not cite this workspace run as an SSCD-active inference run.

FastAPI can start in this container. The container's Node runtime cannot start `next dev` because its sandbox
denies network-interface enumeration (`uv_interface_addresses`); this is an execution-environment limitation,
not a TypeScript/build failure. Production compilation completes successfully.

## What is not yet scientifically established

This snapshot does **not** establish a universal accuracy percentage, a calibrated probability, or a legal
infringement classifier. The current operating points require a larger held-out deployment-domain benchmark.
Use `scripts/benchmark_copy_fusion.py` and report positive recall, false-positive rate, review rate,
per-transformation failures, and confidence intervals before production promotion.

The learned style lane remains experimental. CSD stays optional because its upstream repository continues to
display a checkpoint-discrepancy warning. IntroStyle/DiffSim/ALADIN are retained as model-tournament
challengers in `V05_RESEARCH_AND_REPO_MAP.md`, not falsely reported as active providers.
