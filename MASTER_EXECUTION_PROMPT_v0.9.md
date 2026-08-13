# CreatorProof v0.9 — master execution, activation, calibration, and UX audit prompt

Copy everything below the divider into an agentic IDE opened at the extracted `creatorproof`
repository root.

---

You are the lead engineer and validation auditor for **CreatorProof v0.9.0**, build signature
`PLAIN-SCORE-WATERMARK-2026.08.09`. Run this repository end to end, activate the legitimate local
model integrations, test the exact failure cases listed below, and report only observed evidence.
Never invent an active model, benchmark score, blockchain transaction, OCR result, or browser check.

## Non-negotiable product semantics

CreatorProof answers three separate questions:

1. Was AI likely involved?
2. Does the candidate reuse a particular stored work?
3. Does different content unusually resemble a registered creator profile?

Never turn these into an infringement percentage. `NO_MATCH_IN_CHECKED_SOURCES` applies only to the
declared catalog. It must never suppress or rewrite the AI-origin result. “No strong AI indicators”
is not “human-made.” A visible AI label is review evidence, not provenance. A missing label or C2PA
manifest is neutral. Style resemblance does not prove model training or copying.

Do not tune a threshold until one screenshot gets the desired result. Record misses as false
negatives, add them to a frozen evaluation partition, and change a model or operating point only when
the broader locked validation evidence improves.

## Phase 0 — confirm the correct archive and protect the workspace

Read `README.md`, `BUILD_INFO.md`, `.env.example`,
`docs/V09_ORIGIN_SCORE_AND_PRODUCT_UI.md`, `docs/V07_VALIDATION_PROTOCOL.md`, and every applicable
`AGENTS.md`. Preserve user files and unrelated changes. Never reset or broadly delete the workspace.

Confirm these exact source markers:

```text
API/Web version: 0.9.0
Build signature: PLAIN-SCORE-WATERMARK-2026.08.09
Origin provider: evidence-family-synthetic-ensemble-v3
Origin schema: creatorproof.synthetic_origin.v3
Visible-label provider: tesseract-visible-ai-marker-v1
```

If they are absent, stop: the wrong archive is open. Record OS, CPU/GPU, Python, `uv`, Node, npm,
Git, Git-LFS, Tesseract, and available CUDA versions. Search tracked files for secret-shaped values
without printing secrets.

## Phase 1 — install system requirements

Required: Python 3.12+, `uv`, Node 20.9+, npm, Git, Git-LFS, and Tesseract with English data.

Ubuntu/Debian example:

```bash
sudo apt-get update
sudo apt-get install -y git git-lfs tesseract-ocr tesseract-ocr-eng build-essential
git lfs install
python3 --version
uv --version
node --version
npm --version
tesseract --version
```

Use the platform's official package mechanism on macOS or Windows. Do not download random model
executables from file-sharing sites.

## Phase 2 — local configuration and locked core dependencies

```bash
cd apps/api
test -f .env || cp ../../.env.example .env
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv sync --dev

cd ../web
test -f .env.local || cp .env.local.example .env.local
npm install
```

The frontend file should contain a local API URL and the same development API key as the backend.
Leave `OPENROUTER_API_KEY` blank unless the operator provides one. OpenRouter only explains
structured evidence and can never change detection or policy.

In `apps/api/.env`, keep these visible-label settings active:

```dotenv
CREATORPROOF_VISIBLE_AI_MARKER_MODE=auto
CREATORPROOF_VISIBLE_AI_MARKER_BINARY=tesseract
CREATORPROOF_VISIBLE_AI_MARKER_TIMEOUT_SECONDS=12
CREATORPROOF_VISIBLE_AI_MARKER_MIN_CONFIDENCE=0.42
CREATORPROOF_VISIBLE_AI_MARKER_TERMS_JSON=[]
```

Only add generator-specific text terms after testing editorial-text false positives. Keep the JSON
on one line.

## Phase 3 — activate copy retrieval and learned creator-style analysis

From `apps/api`:

```bash
uv pip install -r requirements-ai.txt
uv run --no-sync python scripts/fetch_sscd_model.py
uv run --no-sync python -m scripts.check_ai

uv pip install -r requirements-style-experimental.txt
uv run --no-sync python -m scripts.fetch_csd_runtime
uv run --no-sync python -m scripts.check_style_ai --require-learned
```

SSCD must report its official provider, 512 finite L2-normalized dimensions, repeatability, and a
recorded weight digest. Learned style must report a finite normalized descriptor and its exact
checkpoint/source revision. Never present raw cosine as a probability. Never enable unsafe legacy
pickle loading without an operator-reviewed hash pin.

## Phase 4 — activate AI-origin family A

```bash
uv pip install -r requirements-synthetic.txt
uv run --no-sync python -m scripts.fetch_community_forensics_model
uv run --no-sync python -m scripts.check_synthetic_ai
```

Acceptance:

- Community Forensics safetensors are active;
- preprocessing is EXIF transpose → RGB → resize the shorter side to 440 → center crop 384 →
  ImageNet normalization;
- provider, evidence family, model version, and SHA-256 are recorded;
- the raw result is labelled not a probability;
- repeated inference is deterministic within tolerance.

## Phase 5 — activate independent AI-origin family B

Use the official Apache-2.0 GRIP repository in an isolated environment:

```bash
cd apps/api
mkdir -p vendor
git clone https://github.com/grip-unina/ClipBased-SyntheticImageDetection.git \
  vendor/ClipBased-SyntheticImageDetection
git -C vendor/ClipBased-SyntheticImageDetection lfs pull
git -C vendor/ClipBased-SyntheticImageDetection rev-parse HEAD

python3 -m venv vendor/ClipBased-SyntheticImageDetection/.venv
vendor/ClipBased-SyntheticImageDetection/.venv/bin/python -m pip install --upgrade pip
vendor/ClipBased-SyntheticImageDetection/.venv/bin/python -m pip install \
  tqdm scikit-learn pillow pyyaml pandas torchvision torch 'timm>=0.9.10' \
  'huggingface-hub>=0.23.0' open_clip_torch scipy
```

Do not overwrite an existing vendor checkout. Inspect its origin, status, license, and commit first.
On Windows use the environment's `Scripts/python.exe` path. Confirm Git-LFS weights are binary
objects, not pointer files.

Add the one-line GRIP adapter JSON from `.env.example`, with paths corrected for this machine. Then:

```bash
uv run --no-sync python -m scripts.check_synthetic_ai
```

It must list two different evidence families. The adapter must read upstream `soft_or_prob` fusion.
Any timeout, missing weight, malformed output, or nonzero process exit fails that provider closed.

## Phase 6 — verify visible-label OCR with real inference

Run the focused real-engine test:

```bash
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run pytest -q \
  tests/test_visible_markers.py::test_real_tesseract_detects_a_clear_ai_generated_label
```

Then create an authorized watermark test folder with at least:

- large and small `AI generated` text;
- black-on-white and white-on-black text;
- translucent corner marks;
- rotated, compressed, resized, and screenshot versions;
- ordinary text with no AI claim;
- generator names used in an article or poster, not as a provenance claim;
- a forged AI label on a human image.

The last item must still produce **review**, never “verified AI provenance.” No visible label must
never lower the origin score or support human origin.

Evaluate PaddleOCR separately if Tesseract recall is inadequate. Do not add it to the main runtime
until a locked OCR benchmark shows a useful recall gain without unacceptable editorial-text false
alerts. Both OCR engines remain one visible-text evidence type.

## Phase 7 — activate C2PA and proof providers

Install an official `c2patool` release and record `c2patool --version`. Preserve trusted,
valid-untrusted, invalid, absent, and unavailable as separate states. A trusted AI assertion may
confirm origin; absence does not clear it.

Local Merkle receipts work without chain credentials and must say **local proof — not blockchain**.
For optional EAS testnet anchoring:

```bash
uv pip install -r requirements-blockchain.txt
```

Use only operator-provided testnet configuration. Never print the signer key or put images,
identities, or evidence on-chain. Attest only the canonical `bytes32 packetHash`. Call it public
blockchain proof only after the receipt is mined, the attestation UID is extracted, validity is
confirmed on-chain, and the committed hash matches locally.

## Phase 8 — run all source and build gates

```bash
cd apps/api
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run ruff check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run ruff format --check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run pytest -q

cd ../web
npm run typecheck
npm run build
```

Do not disable tests, weaken assertions, or install a random major dependency to force a pass.
Record non-failing warnings separately.

Explicitly verify:

1. origin runs when the catalog is empty;
2. origin runs when the catalog is non-empty but no work matches;
3. an explicit visible AI label routes the case to review even with no active model;
4. a missing or failed label check is neutral;
5. no active detector says unavailable, not human;
6. one uncalibrated quiet detector abstains;
7. only two independent, calibrated, stable quiet families can say no strong indicators;
8. strong disagreement, low resolution, or transformation instability abstains;
9. a no-match catalog result never suppresses a positive or uncertain origin result;
10. unresolved origin changes an otherwise source-scoped catalog pass into product review;
11. visible-label boxes are normalized and displayed over the correct image location;
12. AI signal and evidence quality are never labelled probabilities.

## Phase 9 — build lawful calibration, validation, and locked-test partitions

Create physically separate manifests. Split by source lineage and generator; no derivative or
near-duplicate may cross partitions. Include unseen modern generators, human digital-art hard
negatives, AI-retouched human images, human-retouched AI images, social delivery transformations,
text-heavy graphics, and difficult visible-label cases.

Collect raw provider/version scores and fit held-out calibration:

```bash
cd apps/api
uv run --no-sync python -m scripts.collect_synthetic_calibration_scores \
  /absolute/path/calibration-manifest.json \
  --output /absolute/path/calibration-scores.json

uv run --no-sync python -m scripts.calibrate_synthetic_scores \
  /absolute/path/calibration-scores.json \
  --output models/synthetic-calibration.json \
  --minimum-per-class 25

uv run --no-sync python -m scripts.check_synthetic_ai
```

The built-in minimum is a software guard, not a claim that 25 samples per class are adequate. Use a
substantially larger, representative corpus. Any model, preprocessing, model-version, or deployment
domain change invalidates calibration.

## Phase 10 — run the model tournament and locked benchmark

Start with existing Community Forensics and GRIP. Evaluate GAPL, image-adaptive prompt learning,
Difference-in-Difference, and any NTIRE-reproduced candidate only through isolated JSON adapters.
QuAD is a research reference for quality-aware near-duplicate aggregation; inspect its license before
commercial use. Keep every promising repository in the report, including research-only candidates,
but label legal and operational constraints accurately.

Promote a detector only when it adds error diversity and improves locked selective risk. Report:

- ROC-AUC and average precision;
- FPR at 95% TPR and TPR at 1% FPR;
- abstention, selective coverage, and selective accuracy;
- expected calibration error or reliability plot;
- worst-generator recall and worst-human-source false-positive rate;
- Wilson or bootstrap confidence intervals;
- latency and peak memory on the demo machine;
- exact provider versions, commits, hashes, calibration ID, and test ID.

Run:

```bash
uv run --no-sync python -m scripts.benchmark_synthetic_detection \
  /absolute/path/locked-test-manifest.json \
  > /absolute/path/v09-origin-benchmark.json
```

Respect the script's `SMOKE_TEST_ONLY` support gates. Never report a selected-image result as model
accuracy.

## Phase 11 — launch clean services

Stop only processes proven to belong to this checkout. Do not use broad `pkill` commands.

Backend terminal:

```bash
cd apps/api
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run uvicorn app.main:app \
  --host 127.0.0.1 --port 8001
```

Frontend terminal:

```bash
cd apps/web
CREATORPROOF_API_URL=http://127.0.0.1:8001 npm run dev -- --port 3001
```

Check:

```bash
curl -s http://127.0.0.1:8001/healthz
curl -s http://127.0.0.1:3001/api/health
```

Both must report v0.9.0. Backend health must show the build signature, active origin families, and
visible-marker state.

## Phase 12 — mandatory end-to-end cases

Use authorized originals, never just screenshots of the application.

1. **Empty catalog, known AI image:** the origin lane still produces a result and scorecard.
2. **Non-empty catalog, known AI image with no match:** the nearest reference may appear, but the
   case action remains origin review when origin is positive/uncertain.
3. **Clear visible AI label, models silent:** label is highlighted; product says review; no
   provenance claim is made.
4. **Visible label absent:** absence contributes no negative score.
5. **Known AI positive without label:** evaluate two learned families and record any false negative.
6. **Human hard negative:** confirm the system does not overreact to illustration, smooth gradients,
   heavy edits, or generator names used as ordinary text.
7. **Same-work retouch:** work-match lane finds the correct reference and verified areas.
8. **Unrelated image:** no invented region or correspondence appears.
9. **Cross-content style positive:** style lane can review while work-match correctly rejects.
10. **Unresolved origin:** API `policy_action` is `REVIEW`, not a contradictory catalog pass.

For every case save the input lineage, expected label, actual plain result, AI signal, evidence
quality, family scores, stability, calibration state, catalog outcome, screenshot, and packet hash.

## Phase 13 — browser and accessibility audit

Verify at desktop and 390px mobile width with mouse and keyboard:

- a new reviewer can state the result and next action within five seconds;
- fonts are comfortably readable without zoom;
- summary, AI, work match, and creator profile are the only primary views;
- detailed structure and style map are secondary controls;
- the two scores explain themselves and remain visually distinct;
- technical model/provider details are closed by default;
- focus indicators, labels, status announcements, contrast, and disabled states work;
- long titles, filenames, reason text, and 200% browser zoom do not overflow;
- a visible label box aligns with the actual text after responsive scaling.

Do not claim this phase passed without opening and interacting with the live UI.

## Phase 14 — final report

Return:

1. environment versions;
2. active/inactive provider table with exact model hashes and reasons;
3. all quality-gate commands and results;
4. real OCR test matrix;
5. all ten E2E cases;
6. locked benchmark metrics and promotion state;
7. desktop/mobile/accessibility observations;
8. proof provider status and transaction link only if genuinely mined;
9. failures and remaining blockers;
10. an honest release statement.

Allowed promotion labels:

- `SOURCE_VERIFIED`: static/build/test gates pass;
- `RUNTIME_READY`: named model artifacts are active and real E2E cases pass;
- `DEMO_READY`: runtime plus browser and rehearsed demo cases pass;
- `DOMAIN_CALIBRATED`: frozen calibration and locked disjoint evaluation pass declared gates;
- `PRODUCTION_VALIDATED`: a separately approved customer-domain validation and operational review
  are complete.

Do not use a higher label without its evidence. Universal or “perfect” AI-image detection is not an
allowed release claim.
