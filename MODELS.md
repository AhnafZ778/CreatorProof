# Models

How CreatorProof’s AI actually works, written for the BCOLBD AI finals rubric:
architecture, algorithms, preprocessing, training, validation, and a
reproducible inference path.

If you only read one file besides the README, read this one.

---

## 1. What was developed

CreatorProof is an **inference system**, not a newly trained network.

We did not collect a training set and we did not fine-tune SSCD, Community
Forensics, or CSD. Those checkpoints stay official. What this repository
implements is:

1. Three **separate** evidence lanes (copy, origin, profile).
2. Official preprocessing, byte-pinned artifacts, and explicit fallbacks.
3. Fusion rules that a high embedding score cannot override.
4. A Model Lab that records identity, SHA-256, and qualification state.

A judge reproducing the project is reproducing **this pipeline**, with the same
weights the cards name.

Current bundle: `RUNTIME_READY`
(`apps/api/model_lab/bundles/creatorproof-runtime-ready-v1.json`).
That means the pinned files load and the local probes pass. It does **not**
mean we have a held-out, domain-calibrated accuracy number for a customer
corpus.

---

## 2. Architecture

One image in. Three lanes. Policy last.

```text
image
  ├─ Copy      SSCD retrieve → MAGSAC verify → aligned structure → fuse
  ├─ Origin    C2PA / OCR / Community Forensics (optional Sightengine) → fuse
  └─ Profile   CSD or diagnostic style → catalog-relative readout
                    ↓
              evidence packet (hashes, providers, coverage)
                    ↓
              policy: PASS / REVIEW / BLOCK
```

Lanes do not vote into one confidence score. A copy match cannot hide an origin
finding. Policy cannot change a lane’s evidence.

Serving: FastAPI inference + worker, Next.js UI, optional Redis/Postgres.
Live demo: https://creatorproof.uaenorth.cloudapp.azure.com/

---

## 3. Algorithms, preprocessing, code

### Copy lane — “does this reuse a registered work?”

| Step | Method | Preprocessing | Code |
| --- | --- | --- | --- |
| Retrieve | SSCD DISC Mixup, 512-d cosine. Whole image plus five overlapping regions nominate candidates. | RGB, shortest side 288, ImageNet normalize | [`ai_retrieval.py`](apps/api/app/providers/ai_retrieval.py) |
| Verify | SIFT, ORB fallback; USAC/MAGSAC homography; inliers, coverage, symmetric transfer error | Grayscale local features | [`geometry.py`](apps/api/app/providers/geometry.py) |
| Corroborate | After a valid homography: luminance/gradient correlation, GMS, SSIM on the support region | Warp under the validated homography | [`aligned_perceptual.py`](apps/api/app/providers/aligned_perceptual.py) |
| Fuse | Exact SHA-256 is an exact copy. Otherwise MATCH requires geometry **and** structure. SSCD/pHash corroborate; they cannot MATCH alone. | — | [`copy_fusion.py`](apps/api/app/services/copy_fusion.py) |

Artifact: official `sscd_disc_mixup.torchscript.pt`
SHA-256 `9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56`
Card: [`sscd-disc-mixup.md`](apps/api/model_lab/cards/sscd-disc-mixup.md)

Without that file the lane uses pHash and writes the fallback into the packet.

### Origin lane — “what evidence of generative AI?”

| Signal | Method | Preprocessing | Code |
| --- | --- | --- | --- |
| Provenance | Official `c2patool`. Missing manifest = unknown, not “human.” | Original bytes | [`provenance.py`](apps/api/app/providers/provenance.py) |
| Visible label | Tesseract OCR on the full image and corners. A found “AI” label forces review; absence is neutral. | Grayscale views | [`visible_markers.py`](apps/api/app/providers/visible_markers.py) |
| Pixel detector | Community Forensics ViT-S/384 (safetensors) | **Official eval:** shorter side 440, center crop 384 | [`synthetic_detection.py`](apps/api/app/providers/synthetic_detection.py) |
| Optional vendor | Sightengine `genai`, one upload of the original. Local models run only if that call fails. A low vendor score is not “shopped” against local scores. | Original media | same file |

Artifact: `OwensLab/commfor-model-384`
SHA-256 `b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387`
Card: [`community-forensics-384.md`](apps/api/model_lab/cards/community-forensics-384.md)

Quiet detector output is not proof of human origin. Uncalibrated scores are not
shown as percentages.

### Profile lane — “does this resemble a registered creator?”

| Path | Method | Notes |
| --- | --- | --- |
| Learned (optional) | CSD ViT-L + CSLS readout | Experimental. Upstream warns about a weight discrepancy. Off unless fetched. |
| Default | Palette, luminance, edges, texture | Always available. Packet says `learned=false`. Cannot attribute a creator. |

Consent-backed profile manifests only. A small catalog cannot mint a
high-confidence attribution.

Card: [`csd-vit-l.md`](apps/api/model_lab/cards/csd-vit-l.md)

---

## 4. Training process

**There is no training run in this repository.**

| Model | Who trained it | What we do |
| --- | --- | --- |
| SSCD DISC Mixup | Meta / SSCD authors | Load official TorchScript, pin SHA, retrieve |
| Community Forensics 384 | Owens Lab | Load official safetensors, pin SHA, official crop |
| CSD ViT-L | CSD authors | Optional adapter; not required for the demo |
| Fusion / geometry / diagnostics | This codebase | Deterministic rules, not a learned classifier |

Retraining those networks would need datasets and licenses we do not have, and
would make our bytes incomparable to the published checkpoints. The product
decision was to pin the official artifacts and spend the work on verification,
scope, and honest failure.

That is the training-process answer for this submission.

---

## 5. Validation and reproducibility

| Check | Command (from `apps/api`) | What it proves |
| --- | --- | --- |
| Bundle identity | `python -m scripts.validate_model_bundle` | Cards, hashes, and lock file agree |
| SSCD loads | `python -m scripts.check_ai` | 512-d unit vector, repeat similarity ~1 |
| Origin loads | `python -m scripts.check_synthetic_ai` | Community Forensics runs, deterministic |
| Copy / origin / style benches | `python -m scripts.benchmark_*` | Metrics on a **labelled** manifest |
| Tiny runs | report grade `SMOKE_TEST_ONLY` | Cannot be sold as production accuracy |

From the repo root, `make inference` runs the two load probes after fetching
the pinned weights.

We do not ship a customer corpus. Benchmark media stays outside Git and is
addressed by SHA-256 in `apps/api/benchmarks/`. Until a held-out, leakage-controlled
report is sealed, do not read any UI number as a published accuracy.

Qualification ladder (cannot skip rungs):
`SOURCE_VERIFIED` → `RUNTIME_READY` → `SMOKE_TEST_ONLY` → `DEMO_READY` →
`CALIBRATED_DOMAIN_READY` → `PRODUCTION_READY`.
This checkout is on `RUNTIME_READY`.

---

## 6. Rubric map

| BCOLBD AI finals item | Where it is |
| --- | --- |
| Architecture | This file, §2; diagrams in `submission/architecture-packs/` |
| Algorithms | §3 and the files in the tables |
| Data preprocessing | §3 (288 / 440→384 / CSD upstream transform) |
| Training process | §4 |
| Validation methods | §5 |
| Showcasing the models | This file + `apps/api/model_lab/cards/` |
| Deployment-ready inference | `make inference` and the live demo |
| Reproducibility | SHA-256 in the cards; fetch scripts refuse a digest mismatch |

---

## 7. Limits (read these as part of the model, not as footnotes)

- Copy retrieval can confuse shared templates, repeated graphics, and a visual tradition. That is why geometry can reject a high SSCD score.
- Origin detectors drift under compression, screenshots, and unseen generators.
- Style resemblance is catalog-relative. It is not biometrics.
- Nothing here is a legal conclusion.

Math write-ups, if you want the equations: [`docs/V07_DETECTION_MATH.md`](docs/V07_DETECTION_MATH.md), [`docs/V06_STYLE_EVIDENCE_MATH.md`](docs/V06_STYLE_EVIDENCE_MATH.md).
