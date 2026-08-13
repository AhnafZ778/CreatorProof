# CreatorProof v0.4 — master agentic execution prompt

Copy everything below this line into the coding agent that has access to the extracted repository.

---

You are validating CreatorProof **v0.4.0 / DUAL-LANE-2026.08.09**. Work from the repository root.
Do not silently weaken tests, thresholds, evidence semantics, or fail-closed behavior. Never claim a
model ran unless health/evidence output proves it. Never describe style similarity as proof of copying,
training-data use, authorship, or infringement.

## Goal

Bring the complete local stack up, activate SSCD copy retrieval, attempt the optional experimental CSD
creator-style provider, run all quality gates, then exercise both independent lanes:

- Copy lane: SHA-256 / pHash / SSCD -> ORB + USAC/MAGSAC verification.
- Style lane: creator style embeddings -> multi-work creator prototypes -> style-nearest exemplar,
  plus transparent palette/tone/stroke/texture diagnostics.

The four UI modes must be exactly: **Overview**, **Copy localization**, **Style signature**,
**Cross-content style map**. There must be no old geometry-aligned overlay/difference tab.

## 1. Inspect and install

Report exact versions of Python, uv, Node, and npm. Then:

```bash
cd apps/api
uv sync --dev
uv pip install -r requirements-ai.txt
cp ../../.env.example .env
uv run --no-sync python -m scripts.fetch_sscd_model
uv run --no-sync python -m scripts.check_ai
```

`check_ai` must report SSCD available, 512 dimensions, unit L2 norm, and repeat similarity 1 before
you call copy AI active.

Attempt the learned style runtime separately:

```bash
uv pip install -r requirements-style-experimental.txt
uv run --no-sync python -m scripts.fetch_csd_runtime
uv run --no-sync python -m scripts.check_style_ai --require-learned
```

Record the exact CSD repository commit and checkpoint SHA-256. If installation/model loading fails,
do not fake success: capture the actual error and continue with the transparent
`diagnostic-style-signature-v1` fallback. Note that the upstream CSD repository currently warns that
its uploaded weights are under investigation for a discrepancy with paper results; even a successful
load remains experimental until benchmarked.

Frontend:

```bash
cd ../web
npm install
```

Keep `OPENROUTER_API_KEY` blank unless a key is already intentionally configured. The optional
OpenRouter explainer must never be required for detection.

## 2. Run quality gates

```bash
cd ../api
uv run ruff check app tests scripts
uv run ruff format --check app tests scripts
uv run pytest -q

cd ../web
npm run typecheck
npm run build
```

Expected repository baseline is 9 backend tests. Do not change code merely to force this expected
count; report the actual count and any legitimate new tests.

## 3. Start clean local services

Use ports 8001 and 3001 unless already occupied by unrelated user processes. Do not kill unrelated
processes. If you use 8001, set `apps/web/.env.local` so `CREATORPROOF_API_URL=http://localhost:8001`.
Then start:

```bash
cd apps/api
uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001
```

and in a second terminal:

```bash
cd apps/web
npm run dev -- -p 3001
```

Verify `/healthz` and `/api/health`. Required API version is `0.4.0`. Report copy provider and style
provider independently. `style_available=true` does not mean learned AI is active; require
`style_learned=true` for that claim.

## 4. End-to-end copy-lane acceptance

Register at least three visually distinct works. Scan:

1. an exact copy;
2. a crop/resize/JPEG recompression of one registered work;
3. a genuinely unrelated hard negative.

For the transformed positive, inspect retrieval rank, SSCD cosine, geometry validation, inliers,
coverage, transfer/reprojection errors, emitted regions/correspondences, and evidence-packet hash.
For the hard negative, geometry must fail closed and emit zero copy-localization regions/pair lines.
Nearest-reference display alone is not a match.

## 5. End-to-end creator-style acceptance

Create at least two creator profiles and register **3+ representative works per creator** by using the
exact same `claimant`/Creator-style-profile value for each creator. Use genuinely different
compositions within each creator profile; do not build the style demo entirely from crops of one image.

Scan a held-out, unregistered image whose expected creator/style label is known. Inspect:

- `evidence_packet.style_analysis.provider`;
- `learned_provider_active`;
- `calibration_state`;
- `top_profiles[0].creator` and `sample_count`;
- prototype and exemplar similarity;
- top-vs-runner-up margin;
- transparent diagnostic factor values;
- 4x4 candidate/reference style-map cells.

It is valid for copy geometry to reject this image while the style profile ranks correctly. That is
the exact use case v0.4 adds.

If there is no labelled real style dataset available locally, do **not** invent a style-accuracy
number. State that functional plumbing was tested but learned style effectiveness remains unmeasured.

## 6. Style benchmark gate

Build a manifest as documented in `docs/STYLE_SIMILARITY_AND_ATTRIBUTION.md`, with different-content
held-out queries and difficult related-style negatives. Then run:

```bash
cd apps/api
uv run --no-sync python -m scripts.benchmark_style_retrieval \
  /absolute/path/to/manifest.json --require-learned
```

Report Top-1 creator accuracy, Recall@K, mean top-vs-runner-up margin, per-creator discrimination gaps,
negative-gap count, reference/query counts, and provider. Never generalize a tiny synthetic benchmark
to a universal accuracy claim. The 2026 CSD+ work makes corpus diagnostics especially important; if
raw CSD shows weak/negative creator discrimination gaps, evaluate CSLS readout before setting a review
threshold.

## 7. Browser/UI audit

Open the app and visually verify:

- obvious v0.4 build identity;
- Creator / style profile field on registration;
- Overview distinguishes Copy lane from Creator style lane;
- Copy localization explains what ORB pairs mean and shows none when geometry rejects;
- Style signature switches the right image to the style-nearest exemplar and shows creator sample
  count/provider/calibration plus transparent factor bars/palettes;
- Cross-content style map contains no geometric connection lines and explains that tile positions need
  not correspond;
- old geometry overlay/difference views are absent;
- OpenRouter explanation, if configured, says the lanes are independent and never changes a score.

## 8. Final report format

Return:

1. Runtime versions/endpoints.
2. Copy provider state and SSCD smoke check.
3. Style provider state, exact CSD commit/checkpoint digest if active, and the upstream warning.
4. Backend/frontend gate results.
5. Copy positive/hard-negative evidence.
6. Style functional test results.
7. Style benchmark results, or explicitly `NOT MEASURED — NO LABELLED CORPUS`.
8. UI audit results for all four modes.
9. Blockchain/C2PA status honestly (provider slots are not live transactions).
10. Remaining blockers and the single highest-value next experiment.

Do not end with “perfect” or “100% accurate.” End with a precise verdict such as
`DEMO READY — COPY LANE MEASURED, STYLE LANE FUNCTIONAL/UNCALIBRATED` or the actual weaker state the
evidence supports.
