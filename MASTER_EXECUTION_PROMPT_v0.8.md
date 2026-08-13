# CreatorProof v0.8 — master execution, activation, and audit prompt

Copy everything below the divider into an agentic IDE opened at the extracted `creatorproof`
repository root.

---

You are the lead engineer, model-integration owner, and validation auditor for **CreatorProof
v0.8.0**, build signature `CLEAR-ORIGIN-ENSEMBLE-2026.08.09`. Execute the project end to end. Work
autonomously within this repository, preserve user work, and report actual evidence only. Never
invent a command result, active model, benchmark score, blockchain transaction, or browser
observation.

## Mission and non-negotiable semantics

CreatorProof answers three separate questions:

1. **Origin:** are there reproducible AI-generation indicators or trusted provenance assertions?
2. **Copy:** is there corroborated evidence that a particular registered work was reused?
3. **Style:** does a different-content candidate unusually resemble a creator's multi-work profile?

Do not combine these into an “infringement percentage.” A detector score is not automatically an AI
probability. “No strong AI indicators found” is not “human-made.” Style resemblance does not prove
training-data use. Same-work evidence is not a legal conclusion. A missing C2PA manifest is unknown,
not human provenance. A local Merkle receipt is not a blockchain transaction.

Do not tune thresholds until one supplied screenshot produces a desired answer. If a known AI image
is missed, record a false negative, verify preprocessing/model activation, add the case to a locked
evaluation set, and improve only against a broader calibration/validation split.

## Phase 0 — protect and inspect the workspace

1. Read completely:
   - `README.md`
   - `BUILD_INFO.md`
   - `.env.example`
   - `docs/V08_ORIGIN_DETECTION_AND_UI.md`
   - `docs/V07_VALIDATION_PROTOCOL.md`
   - `docs/V07_DETECTION_MATH.md`
   - `docs/V07_REPOSITORY_PLAYBOOK.md`
2. Read every applicable `AGENTS.md`. For Next.js work, read the relevant installed documentation in
   `apps/web/node_modules/next/dist/docs/` before editing.
3. Inspect repository status. Preserve all existing and unrelated changes. Never reset or broadly
   delete the workspace.
4. Record OS, CPU/GPU, Python, `uv`, Node, npm, Git, and Git-LFS versions.
5. Search tracked files for accidental secrets without printing secret values. Never display API,
   RPC, signing, or OpenRouter keys.
6. Confirm these source markers before proceeding:

```text
API/Web version: 0.8.0
Build signature: CLEAR-ORIGIN-ENSEMBLE-2026.08.09
Origin provider: evidence-family-synthetic-ensemble-v2
Origin schema: creatorproof.synthetic_origin.v2
```

If these markers are absent, stop and report that the wrong archive is open.

## Phase 1 — create local configuration without embedding credentials

From the repository root:

```bash
cd apps/api
cp -n ../../.env.example .env
cd ../web
test -f .env.local || cp .env.local.example .env.local
```

If the frontend example is absent, create `.env.local` containing only:

```dotenv
CREATORPROOF_API_URL=http://127.0.0.1:8001
CREATORPROOF_API_KEY=change-me-before-sharing
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
```

Keep the backend and frontend development API keys equal. Generate a strong key before any shared
deployment. Do not invent an OpenRouter key; the optional explainer is independent of detection.

## Phase 2 — install locked core dependencies

Use Python 3.12+ and Node 20.9+ unless the lockfiles state a stricter requirement.

Backend:

```bash
cd apps/api
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv sync --dev
```

Frontend:

```bash
cd ../web
npm install
```

Use `package-lock.json` and `uv.lock`. Report incompatibilities instead of silently replacing major
framework or ML versions.

## Phase 3 — activate copy retrieval and learned style providers

From `apps/api`:

```bash
uv pip install -r requirements-ai.txt
uv run --no-sync python scripts/fetch_sscd_model.py
uv run --no-sync python -m scripts.check_ai

uv pip install -r requirements-style-experimental.txt
uv run --no-sync python -m scripts.fetch_csd_runtime
uv run --no-sync python -m scripts.check_style_ai --require-learned
```

SSCD acceptance:

- provider `sscd-disc-mixup-torchscript` is available;
- 512 finite, L2-normalized dimensions;
- deterministic repeat similarity near 1;
- weight SHA-256 recorded.

Style acceptance:

- a learned CSD provider is active, not the diagnostic fallback;
- embedding is finite, non-zero, normalized, and repeatable;
- checkpoint and source revision are recorded;
- raw style cosine is not represented as a probability.

Never load an untrusted pickle checkpoint. If a legacy CSD file is strictly required, first pin its
SHA-256 and follow the opt-in controls documented in `.env.example`.

## Phase 4 — activate origin family A with the official transform

From `apps/api`:

```bash
uv pip install -r requirements-synthetic.txt
uv run --no-sync python -m scripts.fetch_community_forensics_model
uv run --no-sync python -m scripts.check_synthetic_ai
```

Acceptance for Community Forensics:

- provider `community-forensics-vit-small-384` is active;
- safetensors are used; no pickle is loaded;
- the weight SHA-256 is recorded;
- evidence family is `SEMANTIC_GENERATOR_GENERALIZATION`;
- preprocessing is EXIF transpose → RGB → resize shorter side to 440 with bilinear interpolation →
  center crop 384 → ImageNet normalization;
- repeat inference is deterministic within tolerance;
- the diagnostic output explicitly says its raw signal is not an accuracy test or probability.

Run the preprocessing regression test specifically:

```bash
uv run pytest -q tests/test_synthetic_origin.py::test_community_forensics_preprocessing_matches_official_resize_then_center_crop
```

If the model is absent or fails to load, the UI must say the check is unavailable. Do not proceed to
an AI-origin demo with a fallback while claiming the learned model is active.

## Phase 5 — activate independent origin family B (official GRIP CLIPDet)

The archive intentionally does not embed third-party weights. Install the official Apache-2.0 GRIP
repository under `apps/api/vendor` and record its commit:

```bash
cd apps/api
mkdir -p vendor
git clone https://github.com/grip-unina/ClipBased-SyntheticImageDetection.git \
  vendor/ClipBased-SyntheticImageDetection
git -C vendor/ClipBased-SyntheticImageDetection lfs pull
git -C vendor/ClipBased-SyntheticImageDetection rev-parse HEAD
```

If the directory already exists, do not overwrite it. Inspect its origin and clean status, then fetch
only with user-authorized network access. Create an isolated runtime so CLIPDet cannot destabilize
the API lockfile:

```bash
python3 -m venv vendor/ClipBased-SyntheticImageDetection/.venv
vendor/ClipBased-SyntheticImageDetection/.venv/bin/python -m pip install --upgrade pip
vendor/ClipBased-SyntheticImageDetection/.venv/bin/python -m pip install \
  tqdm scikit-learn pillow pyyaml pandas torchvision torch 'timm>=0.9.10' \
  'huggingface-hub>=0.23.0' open_clip_torch scipy
```

On Windows, use
`vendor/ClipBased-SyntheticImageDetection/.venv/Scripts/python.exe` instead. Verify the upstream
weights directory contains the Git-LFS objects, not pointer text.

In `apps/api/.env`, set the following as a single JSON line, using the correct isolated Python path
for the OS:

```dotenv
CREATORPROOF_SYNTHETIC_EXTERNAL_DETECTORS_JSON=[{"name":"grip-clipdet","command":"python -m scripts.clipdet_json_adapter --image {image} --repo ./vendor/ClipBased-SyntheticImageDetection --weights ./vendor/ClipBased-SyntheticImageDetection/weights --runner-python ./vendor/ClipBased-SyntheticImageDetection/.venv/bin/python --device cpu","timeout_seconds":180,"evidence_family":"SEMANTIC_PIXEL_HYBRID","source_scope":"CLIP_SEMANTIC_PLUS_FORENSIC_PIXEL_MODELS"}]
```

Run:

```bash
uv run --no-sync python -m scripts.check_synthetic_ai
```

Acceptance:

- exactly two independent families are shown:
  `SEMANTIC_GENERATOR_GENERALIZATION` and `SEMANTIC_PIXEL_HYBRID`;
- GRIP uses its upstream default `soft_or_prob` fusion column;
- the adapter's sigmoid-bounded fused LLR is still labelled raw and uncalibrated;
- a non-zero upstream exit, missing weights, malformed CSV, or timeout fails that provider closed;
- duplicate instances of one family never count as independent corroboration.

Do not add a third detector merely to increase the displayed score. Add one only if a locked,
generator-disjoint model tournament demonstrates incremental error diversity.

## Phase 6 — activate official provenance and optional proof providers

Install an official `c2patool` release through its documented platform mechanism and record:

```bash
c2patool --version
```

C2PA states must remain distinct: trusted, valid-untrusted, invalid, absent, and unavailable. A
trusted AI-use assertion can confirm provenance. Absence cannot clear origin.

The default local, domain-separated Merkle receipt is verifiable but must be labelled “local proof —
not blockchain.” To use an actual EAS testnet anchor, install:

```bash
uv pip install -r requirements-blockchain.txt
```

Then configure only operator-provided testnet RPC, contract, schema UID, disposable signer, recipient,
and explorer values from `.env.example`. Never print a private key, use mainnet money, or place images,
identity, or raw evidence on-chain. Only the canonical evidence packet's `bytes32 packetHash` may be
attested.

Call blockchain active only after the transaction is mined, the `Attested` event yields a UID,
`isAttestationValid(uid)` is true, and the on-chain hash matches the local packet.

## Phase 7 — run all quality gates

Backend:

```bash
cd apps/api
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run ruff check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run ruff format --check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run pytest -q
```

Frontend:

```bash
cd ../web
npm run typecheck
npm run build
```

Fix genuine failures and rerun the full affected gate. Do not weaken assertions, bypass provenance
checks, disable abstentions, or loosen thresholds to make tests pass.

At minimum, explicitly verify these origin behaviors:

1. one uncalibrated raw score of `0.01` becomes limited-coverage inconclusive, never “1% AI” and
   never human origin;
2. no active detector becomes unavailable, not quiet/human;
3. one strong family raises review but cannot independently claim confident origin;
4. two stable independent strong families can report AI indicators;
5. two calibrated independent quiet families can report no strong indicators, with the disclaimer
   that this does not prove human origin;
6. family disagreement, transform instability, low resolution, or partial provider failure abstains;
7. spatial uplift requires at least three supporting crops; one hot crop cannot decide;
8. the GRIP adapter reads the official fused LLR column, not an invented average.

## Phase 8 — build calibration data correctly

Use only authorized images. Create physically separate `calibration`, `validation`, and locked `test`
manifests. Split by original source/lineage and generator; near-duplicates must never cross splits.
The calibration manifest format is:

```json
{
  "dataset_id": "ideathon-digital-art-calibration-v1",
  "domain": "digital-art-and-social-media-delivery",
  "partition": "calibration",
  "images": [
    {
      "path": "relative/path.png",
      "label": 1,
      "generator": "generator-family-name",
      "source": "authorized-source-name",
      "lineage_id": "unique-source-lineage"
    }
  ]
}
```

Collect the **uncalibrated**, provider/model-version scores and fit Platt calibration:

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

For a credible demo, prefer substantially more than the code's minimum support. Include:

- several modern generators not present in final test;
- human digital art, illustration, photography, scans, and graphic design;
- AI-retouched human work and human-retouched AI work;
- JPEG/WebP, screenshots, social-media resize, crop, blur, sharpen, and color edits;
- difficult real negatives containing smooth gradients, stylization, repetitive texture, and heavy
  post-processing.

Changing model weights, provider version, preprocessing, or target domain invalidates calibration.

## Phase 9 — run the locked origin benchmark

Run only after calibration is frozen:

```bash
uv run --no-sync python -m scripts.benchmark_synthetic_detection \
  /absolute/path/locked-test-manifest.json \
  > /absolute/path/v08-origin-benchmark.json
```

Treat the run as `SMOKE_TEST_ONLY` unless all script support gates pass. Report:

- ROC-AUC and average precision;
- FPR at 95% TPR and TPR at 1% FPR;
- abstention, selective coverage, and selective accuracy;
- Wilson 95% interval;
- confusion counts on decided cases;
- worst-generator and worst-real-source performance;
- latency on CPU and available GPU;
- provider/model hashes and the exact calibration dataset identifier.

A selected example is not a benchmark. If the user's known-AI sample is scored weakly, include it as
a failure case and inspect, in order: model/provider activation, official preprocessing, output
direction, source lineage leakage, image resolution, delivery-view stability, crop consensus, and
family disagreement. Do not alter a threshold until the locked validation set supports the change.

## Phase 10 — start clean services

Identify processes bound to ports 8001 and 3001. Stop only services proven to belong to this checkout;
never use broad process kills.

Backend terminal:

```bash
cd apps/api
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Frontend terminal:

```bash
cd apps/web
CREATORPROOF_API_URL=http://127.0.0.1:8001 npm run dev -- --port 3001
```

Health:

```bash
curl -fsS http://127.0.0.1:8001/healthz
curl -fsS http://127.0.0.1:3001/api/health
```

Require version `0.8.0`. Confirm SSCD, learned style, both origin evidence families, C2PA, and proof
providers separately. Model loading without a labeled benchmark is `RUNTIME_READY`, not accuracy
validation.

## Phase 11 — end-to-end cases

Use authorized images outside the repository archive. Register multiple works and creators, then run:

### A. AI-touched same work

- source retrieval rank 1;
- exact/geometry/aligned-structure copy evidence shown separately;
- origin evidence handled independently;
- side-by-side images render;
- no style score is used to create a copy match.

### B. Known AI-generated, different composition

- run both origin families and delivery/spatial views;
- record raw member outputs, calibration states, family scores, stability, and final state;
- if only one family supports AI, show review/unknown rather than false certainty;
- do not call the image human when both models miss it.

### C. Human hard negative

- no false copy regions;
- origin lane may say no strong indicators only when both families are calibrated and quiet;
- missing C2PA remains unknown evidence.

### D. Family disagreement

- one family high and one low;
- require inconclusive detector disagreement;
- UI explains the disagreement in plain language.

### E. Delivery instability

- use controlled transformations or a test stub;
- require abstention, not a confident label.

### F. AI style imitation without same-work reuse

- copy lane remains negative;
- calibrated multi-work style lane may flag unusual resemblance;
- origin lane is independent;
- joint policy routes review but never says “infringing.”

## Phase 12 — browser and comprehension audit

Open `http://127.0.0.1:3001` in a real browser. Check desktop widths 1440 and 1024, and mobile widths
390 and 375. Use keyboard-only navigation and inspect with a screen reader or accessibility tree when
available.

The default result must pass this five-second comprehension test:

1. one prominent bottom line answers what needs attention;
2. three colored cards clearly answer Origin, Copy, and Style;
3. clicking a card opens that analysis lane and the active state is unmistakable;
4. the origin lane shows conclusion, one-sentence reason, next action, credentials, model coverage,
   and robustness;
5. raw scores, reason codes, provider ledgers, frequency traces, and calibration diagnostics are
   collapsed under **Technical evidence**.

Reject the UI if any raw uncalibrated origin score has a percent sign, if “1% AI” appears, if an
inactive detector looks like a negative result, or if technical telemetry appears above the bottom
line. Verify color contrast, visible focus, no horizontal overflow, descriptive buttons, and an
atomic `role=status` conclusion.

Capture temporary screenshots for the audit but exclude them from the source archive unless the user
explicitly requests them.

## Phase 13 — final audit report

Write `V08_EXECUTION_REPORT.md` containing:

- exact version and build signature;
- every command and real exit status;
- provider names, evidence families, revisions, model hashes, devices, and calibration state;
- complete backend/frontend gate results;
- E2E case results with raw evidence and final plain-language outcomes;
- benchmark support, split rules, metrics, intervals, and worst groups;
- desktop/mobile/accessibility observations;
- proof mode, including why local proof is not blockchain or details of a verified EAS transaction;
- failures, blocked checks, and remaining empirical risks;
- one promotion level: `SOURCE_VERIFIED`, `RUNTIME_READY`, `DEMO_READY`, `DOMAIN_CALIBRATED`, or
  `PRODUCTION_MONITORED`.

Do not use `DEMO_READY` until the named model artifacts are active and real browser/E2E cases are
observed. Do not use `DOMAIN_CALIBRATED` without disjoint calibration and locked-test evidence. Never
write “perfect,” “bulletproof,” “100% accurate,” or “universal detector.”

## Final response format

Lead with the actual promotion level, then provide:

1. quality gates that passed and failed;
2. active and inactive providers;
3. the known-AI sample result and whether it is a recorded false negative;
4. locked benchmark summary with sample counts;
5. five-second UI audit result;
6. proof mode;
7. three highest remaining risks;
8. frontend/backend URLs and paths to the report and benchmark JSON.

