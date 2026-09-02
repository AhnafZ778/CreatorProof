# Models

CreatorProof runs **trained vision models** on a real review job: one image,
three independent questions, a packet a third party can inspect.

This page is the catalog: architecture, algorithms, preprocessing, where the
weights come from, how we validate, and how to reproduce inference.

Live system: https://creatorproof.uaenorth.cloudapp.azure.com/

---

## 1. What the system does

A creative-operations reviewer is about to publish. “Is this safe?” is three
questions with three different failure modes. Averaging them into one percentage
destroys the only information they can act on.

CreatorProof therefore runs three **trained** stacks in parallel, then applies
the customer’s policy last:

1. **Copy** — Meta SSCD finds near-duplicates in the declared catalog; MAGSAC
   geometry has to confirm the region before the system will say MATCH.
2. **Origin** — Community Forensics (and optional Sightengine) plus C2PA and
   visible-label OCR. Missing credentials stay unknown; a quiet score is not
   “this is human.”
3. **Profile** — CSD-style resemblance against consenting creator profiles,
   never mixed into the copy verdict.

What this repository built is the production path around those models:
official preprocessing, SHA-pinned artifacts, regional SSCD, geometry that can
overrule a high embedding, origin fusion, and an evidence packet.

---

## 2. Architecture

```text
image
  ├─ Copy      SSCD retrieve → MAGSAC verify → aligned structure → fuse
  ├─ Origin    C2PA / OCR / Community Forensics (optional Sightengine) → fuse
  └─ Profile   CSD or diagnostic style → catalog-relative readout
                    ↓
              evidence packet (providers, hashes, coverage)
                    ↓
              policy: PASS / REVIEW / BLOCK
```

Lanes do not collapse into one score. A copy match cannot hide origin evidence.
Policy cannot rewrite a lane.

Serving: FastAPI + worker, Next.js UI, optional Redis/Postgres.

---

## 3. Algorithms and preprocessing

### Copy — reuse of a registered work

| Step | Model / method | Preprocessing | Code |
| --- | --- | --- | --- |
| Retrieve | SSCD DISC Mixup (512-d cosine). Whole image plus five overlapping crops. | RGB, shortest side 288, ImageNet normalize | [`ai_retrieval.py`](apps/api/app/providers/ai_retrieval.py) |
| Verify | SIFT, ORB fallback, USAC/MAGSAC homography | Grayscale local features | [`geometry.py`](apps/api/app/providers/geometry.py) |
| Corroborate | Luminance/gradient correlation, GMS, SSIM on the support region | Warp under the validated homography | [`aligned_perceptual.py`](apps/api/app/providers/aligned_perceptual.py) |
| Fuse | Exact SHA-256 → exact copy. Otherwise MATCH needs geometry **and** structure. SSCD/pHash support the finding; they cannot create it alone. | — | [`copy_fusion.py`](apps/api/app/services/copy_fusion.py) |

Checkpoint: official `sscd_disc_mixup.torchscript.pt`  
SHA-256 `9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56`  
Card: [`sscd-disc-mixup.md`](apps/api/model_lab/cards/sscd-disc-mixup.md)

### Origin — generative-AI evidence

| Signal | Model / method | Preprocessing | Code |
| --- | --- | --- | --- |
| Provenance | Official `c2patool` | Original bytes | [`provenance.py`](apps/api/app/providers/provenance.py) |
| Visible label | Tesseract on the full image and corners | Grayscale views | [`visible_markers.py`](apps/api/app/providers/visible_markers.py) |
| Pixel model | Community Forensics ViT-S/384 | Authors’ eval: shorter side 440, center crop 384 | [`synthetic_detection.py`](apps/api/app/providers/synthetic_detection.py) |
| Optional API | Sightengine `genai`, one upload. Local models run only if that call fails. | Original media | same file |

Checkpoint: `OwensLab/commfor-model-384`  
SHA-256 `b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387`  
Card: [`community-forensics-384.md`](apps/api/model_lab/cards/community-forensics-384.md)

### Profile — resemblance to a registered creator

| Path | Model / method | Notes |
| --- | --- | --- |
| Learned | CSD ViT-L + CSLS | Optional; enable with `make inference-style` |
| Default | Palette, luminance, edges, texture | Always on if CSD is not loaded |

Card: [`csd-vit-l.md`](apps/api/model_lab/cards/csd-vit-l.md)

---

## 4. Where the trained weights come from

The copy and origin networks are **already trained**. We deploy the official
releases used in the literature, not a 48-hour retrain that would be weaker
and incomparable to those papers.

| Model | Trained by | How CreatorProof uses it |
| --- | --- | --- |
| SSCD DISC Mixup | Meta (SSCD copy-detection) | TorchScript retrieval, SHA-pinned |
| Community Forensics 384 | Owens Lab | Safetensors origin signal, official crop |
| CSD ViT-L | CSD authors | Optional style descriptors |
| Fusion, MAGSAC gates, diagnostics | This codebase | Deterministic verification around the models |

Weights stay out of Git (size and license). `make inference` fetches the exact
bytes and refuses a SHA mismatch. That is the reproducible training-artifact
story: published checkpoints, locked identity, same inference on a clone as on
the demo.

Bundle: [`creatorproof-runtime-ready-v1.json`](apps/api/model_lab/bundles/creatorproof-runtime-ready-v1.json)

---

## 5. Validation and how to run it

```bash
make inference
```

| Check | Command (from `apps/api`) | What you should see |
| --- | --- | --- |
| Bundle | `python -m scripts.validate_model_bundle` | Cards and hashes agree |
| Copy model | `python -m scripts.check_ai` | `available: true`, 512-d, unit norm |
| Origin model | `python -m scripts.check_synthetic_ai` | Community Forensics loaded |
| Lane benches | `python -m scripts.benchmark_*` | Metrics on a labelled manifest |

The live demo is the same pipeline with the same pins.

---

## 6. Rubric map

| Finals item | Where it is |
| --- | --- |
| Architecture | §2; diagrams in `submission/architecture-packs/` |
| Algorithms | §3 |
| Data preprocessing | §3 (288; 440→384; CSD upstream transform) |
| Training process / model source | §4 — official trained checkpoints, pinned |
| Validation | §5 |
| Inference model | `make inference` + live demo |
| Reproducibility | SHA-256 on each card; fetch refuses a mismatch |

Equations: [`docs/V07_DETECTION_MATH.md`](docs/V07_DETECTION_MATH.md),
[`docs/V06_STYLE_EVIDENCE_MATH.md`](docs/V06_STYLE_EVIDENCE_MATH.md).
