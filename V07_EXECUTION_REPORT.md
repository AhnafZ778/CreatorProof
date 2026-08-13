# CreatorProof v0.7.0 — execution and audit report

Date: 2026-08-09  
Build signature: `TRI-LANE-PROVENANCE-2026.08.09`  
Promotion result in this workspace: **RUNTIME_READY / MODEL ARTIFACT ACTIVATION REQUIRED FOR LIVE AI DEMO**

## 1. What changed from the supplied v0.6 report

The v0.6 report's build checks were useful, but its empirical conclusions were overstated. Style AUC
1.0 used only three queries; copy precision/recall 1.0 used two cases; an unrelated hard negative
received a high style score; and a same-creator/different-content work was allowed to become a copy
match. v0.7 corrects those failure modes rather than lowering thresholds until the screenshots look
convincing.

Implemented:

- independent AI-origin lane;
- official C2PA tool adapter with trusted/untrusted/invalid/absent states;
- Community Forensics safetensors provider and operator TorchScript/external JSON adapters;
- original/JPEG/resize/blur robustness views;
- provider/model-version held-out Platt calibration registry;
- transformation instability, model disagreement, resolution and unavailable-provider abstentions;
- stricter copy fusion requiring aligned structure for all non-identical matches;
- catalog-conditional creator-style conformal tail and positive support gates;
- joint origin/copy/style policy that does not conflate resemblance with infringement;
- local domain-separated Merkle transparency receipts;
- optional real EAS on-chain `bytes32 packetHash` attestation;
- six-mode, colour-coded Evidence Microscope with origin model ledger and proof panel;
- benchmark support gates and selective-risk metrics;
- complete architecture, math, validation, repository, and execution documentation.

## 2. Environment

| Component | Observed version |
| --- | --- |
| Python | 3.12.13 |
| uv | 0.11.33 |
| Node.js | 24.14.0 |
| npm | 11.9.0 |
| Next.js | 16.3.0 |
| CreatorProof API/Web | 0.7.0 |

## 3. Quality gates

Backend commands:

```bash
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run ruff check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run ruff format --check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run pytest -q
```

Result:

- Ruff lint: **PASS**
- Ruff format: **PASS** (65 files checked)
- Pytest: **27/27 PASS**
- Non-failing warning: Starlette TestClient compatibility deprecation from the installed dependency.

Frontend commands:

```bash
npm run typecheck
npm run build
```

Result:

- TypeScript: **PASS**
- Next.js production build: **PASS**
- All static/dynamic routes generated successfully.
- Non-failing environment warning: npm reports the host's legacy `http-proxy` config will change in
  a future npm major release.
- Live browser launch was not counted as verified in this sandbox: `next dev` hit the host/container
  `uv_interface_addresses` system restriction. This is an execution-environment limitation, not a
  passed UI observation; the master prompt requires a real browser check on the target machine.

## 4. Provider state in this packaging workspace

Model weights and credentials are deliberately not embedded in the source archive.

| Provider | State | Reason/next command |
| --- | --- | --- |
| SSCD copy retrieval | Inactive here | Model missing; run `scripts/fetch_sscd_model.py` then `scripts.check_ai` |
| CSD learned style | Inactive here | External repo/checkpoint missing; diagnostic fallback is deterministic and normalized |
| Community Forensics | Inactive here | Safetensors missing; run `python -m scripts.fetch_community_forensics_model` |
| External origin models | None configured | Supply authorized commands through the JSON adapter |
| C2PA | Inactive here | Official `c2patool` is not installed |
| Local Merkle proof | Implemented and tested | Default safe proof when EAS is not configured |
| EAS public anchor | Implemented, not configured | Requires operator-provided testnet RPC/schema/signer |
| OpenRouter explainer | Disabled by blank key | Detection is independent of this optional explainer |

No model-accuracy benchmark is reported from this workspace because the required weights and a
lawfully obtained, generator/creator/source-disjoint dataset are not present. This is the correct
result; it avoids manufacturing another misleading 100% report from toy images.

## 5. Tests added for v0.7

- Stable single-detector AI-origin support.
- Transformation-instability abstention.
- Trusted C2PA AI assertion precedence.
- No-detector behavior never claims human origin.
- Calibration provider/model-version/support gates.
- Merkle inclusion verification, tamper rejection, and invalid-input handling.
- Uncalibrated style high tier suppression.
- Catalog conformal negative-tail and positive-support calculations.
- AI-origin plus calibrated style joint review without a copy match.
- Copy fusion rejection when geometry/SSCD lacks aligned structure.

## 6. Benchmark semantics

`scripts.benchmark_synthetic_detection` now reports:

- ROC-AUC;
- average precision;
- FPR at 95% TPR;
- TPR at 1% FPR;
- abstention rate;
- selective coverage and accuracy;
- Wilson 95% interval;
- decision confusion matrix;
- per-generator/source coverage and selective accuracy.

It labels a run `SMOKE_TEST_ONLY` unless minimum sample, source, generator, and disjointness gates
are met. Copy/style benchmark scripts use the same promotion-state principle.

## 7. Remaining empirical blockers

1. Install and hash-pin SSCD, CSD, Community Forensics, and official c2patool in the target machine.
2. Build an authorized calibration/test corpus that matches the ideathon demo domain and contains
   modern unseen generators, human digital art hard negatives, social-media transformations,
   same-movement creators, retouched copies, and partial reuse.
3. Run the documented model tournament before adding CO-SPY, SSP/ESSP, GAPL, PGC, IntroStyle, or
   DiffSim to production fusion.
4. Create a real EAS testnet schema/transaction if the live presentation needs a public-chain proof.
5. Replace exhaustive catalog retrieval and development authentication before a paid pilot.

## 8. Correct release statement

CreatorProof v0.7 is a source-verified, research-backed prototype with a tested three-lane evidence
architecture, calibratable AI-origin ensemble, fail-closed copy verification, catalog-gated style
evidence, official provenance boundary, and verifiable proof receipts. It becomes **DEMO_READY** on a
machine only after the execution prompt activates the named model artifacts and the end-to-end cases
are observed. Production claims require the separate domain validation protocol.
