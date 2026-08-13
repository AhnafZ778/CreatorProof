# AI retrieval, explanation, and effectiveness validation

This document describes the **copy/derivative retrieval lane** retained in CreatorProof v0.4 and,
just as importantly,
what it does **not** establish.

## 1. Two separate AI roles

### Local SSCD: detection/retrieval

CreatorProof integrates Meta Research's open-source
[SSCD copy-detection project](https://github.com/facebookresearch/sscd-copy-detection) through the
official `sscd_disc_mixup.torchscript.pt` inference artifact linked by that project.

For every registered reference, the API can compute and cache a normalized 512-dimensional SSCD
descriptor. For each candidate scan it computes the same descriptor, takes cosine similarity against
all works in the selected demo catalog, and ranks them descending. The first work is therefore the
nearest registered reference **under this descriptor**, not a guaranteed human-perceptual truth and
not proof of copying.

SSCD is the learned model used by the copy lane. CreatorProof v0.4 adds a separate optional learned
creator-style lane documented in `STYLE_SIMILARITY_AND_ATTRIBUTION.md`; style evidence never changes
the copy lane's geometry verdict.
If the model file or PyTorch is absent, the scan deliberately falls back to pHash and records that
fact in `model_bundle.ai_retrieval_active` / `ai_fallback_reason`.

### OpenRouter: optional explanation only

The Next.js server can send selected structured detector metrics to OpenRouter's chat-completions
API. This produces a plain-language explanation for the Evidence Microscope. It does not receive the
image bytes in this implementation and has no path into retrieval, geometry, `match_status`, or
`policy_action`.

Configure it only if wanted:

```dotenv
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
OPENROUTER_SITE_URL=http://localhost:3000
```

Leaving the key blank is valid. The detector still works.

## 2. Activate and prove the local SSCD path is running

From `apps/api` after the normal `uv sync --dev`:

```bash
uv pip install -r requirements-ai.txt
uv run --no-sync python scripts/fetch_sscd_model.py
uv run --no-sync python -m scripts.check_ai
```

The fetch script downloads the exact public URL linked by the SSCD project and prints the downloaded
file's SHA-256 so you can record the artifact used by a demo/build. It does not claim an upstream
checksum that the project has not supplied here.

The smoke check is successful only when it reports all of the following:

- `available: true`;
- provider `sscd-disc-mixup-torchscript`;
- `embedding_dimensions: 512`;
- `embedding_l2_norm` approximately `1.0`;
- repeat similarity approximately `1.0` for the identical generated input.

Then start the API without re-syncing away the manually installed optional dependency:

```bash
uv run --no-sync uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000/healthz`. `ai_available` must be `true`. After a real scan inspect:

```text
evidence_packet.model_bundle.ai_retrieval_active = true
evidence_packet.model_bundle.retrieval_provider = "sscd-disc-mixup-torchscript"
evidence_packet.matches[0].ai_similarity = <number>
evidence_packet.matches[0].retrieval_rank = 1
```

If those fields do not show SSCD, do not describe that run as AI-powered retrieval.

## 3. What happens with many registered images

For the hackathon-sized catalog the API intentionally performs exhaustive search, not approximate
nearest-neighbor search. That means every reference in the selected tenant/catalog is evaluated and
the SSCD candidate with the highest cosine similarity receives retrieval rank 1. There is no ANN
index recall loss at this prototype scale.

The Evidence Microscope renders that selected reference through an authenticated media endpoint, so
the reference can have been registered before the current browser session. The scan candidate stays
browser-local after the response because the backend's default candidate retention is zero.

An unrelated query still has a mathematically nearest item whenever the catalog is non-empty. The UI
therefore keeps two concepts visually separate:

- `NEAREST_CANDIDATE_ONLY`: retrieval found the nearest item, but geometry did not verify it. Images
  are shown side-by-side and **no** local correspondence callouts are drawn.
- `GEOMETRY_VERIFIED`: the independent local verifier passed its support/coverage/error/sanity gates;
  only then can local correspondence lines and a verified support region appear.
- `EXACT_COPY`: raw SHA-256 is identical.

This separation directly prevents the old failure mode where two unrelated images could be connected
by an impressive-looking random triangle.

## 4. Geometry verifier

The copy-localization verifier is deterministic OpenCV, not a second neural network. It uses:

1. ORB keypoints/descriptors on each image.
2. Lowe-ratio filtering in both directions.
3. Mutual-match intersection.
4. OpenCV `USAC_MAGSAC` homography fitting (RANSAC fallback only if that constant is unavailable).
5. Minimum inlier count and inlier ratio.
6. Convex-hull coverage on **both** images.
7. 4x4 spatial-grid dispersion on **both** images.
8. Forward/backward normalized symmetric transfer error.
9. Homography determinant/conditioning sanity checks.

Failure at any gate sets `validated: false`, records reason codes, and removes correspondence/region
annotations and the visualization homography. The gate values are conservative prototype defaults,
not universal calibrated constants.

## 5. Measure whether the AI is effective

The smoke check proves inference runs; it does **not** prove accuracy. Build a held-out benchmark with
references and queries whose expected source identity you know. Do not let transformations of a
source leak between calibration and final evaluation decisions.

A minimal manifest accepted by the included benchmark tool is:

```json
{
  "references": [
    {"id": "work-a", "path": "references/work-a.png"},
    {"id": "work-b", "path": "references/work-b.png"}
  ],
  "queries": [
    {"path": "queries/work-a-crop.jpg", "expected_reference_id": "work-a"},
    {"path": "queries/unrelated-001.jpg", "expected_reference_id": null}
  ]
}
```

Run:

```bash
uv run --no-sync python -m scripts.benchmark_ai_retrieval path/to/manifest.json --threshold 0.75
```

The script reports:

- top-1 accuracy on known positive queries;
- Recall@5 on known positive queries;
- hard-negative false-alert rate at the supplied similarity threshold;
- the winning reference/similarity for every query so failures can be inspected.

The default `0.75` threshold is an **experimental starting value**, not a guaranteed CreatorProof
operating point. The upstream SSCD README reports results for its own evaluation setting, but those
numbers do not transfer automatically to your customer distribution. Choose CreatorProof thresholds
from your held-out calibration set, then freeze them before final test evaluation.

For a credible hackathon report, include at least these query families: exact copies, resize,
recompression, crop/partial reuse, rotation, perspective/screenshot, mild overlays, collage/partial
content, visually similar but unrelated hard negatives, and ordinary unrelated negatives. Report
latency alongside accuracy.

## 6. Practical acceptance gate for the demo

Do not use a single cherry-picked image pair as validation. At minimum:

1. Register multiple distinct references.
2. Generate/use legitimate transformed test variants of each reference.
3. Confirm the expected reference is rank 1 for those positives.
4. Confirm unrelated images produce no fabricated geometric annotations.
5. Inspect every top-1 failure and add its transformation category to the report.
6. Publish the measured top-1/Recall@5/false-alert metrics with dataset size and threshold.

There is no technically honest way to require 100% accuracy on arbitrary unseen images. CreatorProof's
stronger product behavior is to expose ranking evidence, independently verify localization, abstain
when signals disagree, and measure the operating point on the customer domain.

## 7. Scale-up path

Exhaustive SSCD search is intentionally simple for a one-week prototype. For a large B2B catalog,
retain the same descriptor contract but move vectors to pgvector, Qdrant, FAISS, or another measured
ANN layer. Before promotion, compare ANN Recall@K against the exhaustive result so scale optimization
does not silently reduce retrieval quality.

For harder local verification, benchmark (do not blindly stack) modern candidates such as
[XFeat](https://github.com/verlab/accelerated_features),
[LightGlue](https://github.com/cvg/LightGlue), and
[RoMaV2](https://github.com/Parskatt/romav2). Keep the fail-closed visualization contract regardless
of which verifier wins the project benchmark.
