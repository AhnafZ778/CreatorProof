# CreatorProof v0.9.1 — master execution and latency-validation prompt

Copy everything below into the agentic IDE at the root of the v0.9.1 repository.

---

You are the lead runtime engineer and evidence auditor for **CreatorProof v0.9.1**, build signature
`BATCHED-NONBLOCKING-SCAN-2026.08.09`. Your job is to activate, run, measure, and audit the supplied
code. Do not rewrite detection thresholds or make a slow screenshot look better by changing model
scores. Do not declare success from static checks alone.

## Non-negotiable product boundaries

- AI-origin, registered-work reuse, and creator-style resemblance are separate lanes.
- A visible label is review evidence, not trusted provenance.
- Missing OCR/C2PA/model evidence is neutral or inconclusive, never proof of human origin.
- Origin scores are signal/evidence-quality indicators, not universal AI probabilities.
- Style evidence cannot manufacture a copy match.
- Local Merkle receipts are not blockchain. Only a mined, validated EAS receipt is public-chain proof.
- OpenRouter may explain completed evidence but cannot influence any detector or decision.

## Phase 1 — identify the exact release

1. Read `README.md`, `V091_SCAN_STALL_CORRECTION_REPORT.md`, `.env.example`, and this prompt.
2. Confirm API/Web versions are `0.9.1` and the exact build signature appears in backend health and UI.
3. Report the Python, uv, Node, npm, Git, and Git-LFS versions.
4. Find and stop only stale CreatorProof processes on ports 8000/8001 and 3000/3001. Do not kill unrelated processes.

## Phase 2 — install deterministically

Backend:

```bash
cd apps/api
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv sync --dev
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv pip install -r requirements-ai.txt
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv pip install -r requirements-synthetic.txt
```

Install optional style/blockchain requirements only if those lanes are part of this machine's demo.

Frontend:

```bash
cd apps/web
npm ci
```

If the host prevents writing the default npm cache, use a task-specific cache such as
`NPM_CONFIG_CACHE=/tmp/creatorproof-npm-cache`; do not repurpose `$HOME`.

## Phase 3 — migrate environment safely

1. Back up the current local environment files without printing secrets.
2. Ensure the API environment contains:

```dotenv
CREATORPROOF_JOB_BACKEND=local
CREATORPROOF_LOCAL_JOB_WORKERS=1
CREATORPROOF_SYNTHETIC_EXTERNAL_TIMEOUT_SECONDS=120
CREATORPROOF_VISIBLE_AI_MARKER_TIMEOUT_SECONDS=12
```

3. If GRIP is enabled, change the external command placeholder from `{image}` to `{manifest}` and use:

```text
python -m scripts.clipdet_json_adapter --manifest {manifest} --repo ./vendor/ClipBased-SyntheticImageDetection --weights ./vendor/ClipBased-SyntheticImageDetection/weights --runner-python ./vendor/ClipBased-SyntheticImageDetection/.venv/bin/python --device cpu
```

4. Keep the JSON on one physical `.env` line. Preserve the configured evidence family and source scope.
5. Never print API keys, private keys, RPC credentials, or the full environment.
6. For Docker Compose, leave `CREATORPROOF_JOB_BACKEND=redis`; do not replace the durable worker with a thread.

## Phase 4 — activate and verify model artifacts

Run the existing fetch/check scripts. Hash-pin every downloaded artifact. At minimum:

```bash
cd apps/api
uv run --no-sync python scripts/fetch_sscd_model.py
uv run --no-sync python -m scripts.check_ai
uv run --no-sync python -m scripts.fetch_community_forensics_model
uv run --no-sync python -m scripts.check_synthetic_ai
```

For GRIP, verify the official repository, Git-LFS weights, isolated runner, model names, and one-image
adapter smoke test. Do not report GRIP active if its actual weights were not loaded.

## Phase 5 — static and regression gates

```bash
cd apps/api
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run ruff check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run ruff format --check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-uv-cache uv run pytest -q

cd ../web
npm run typecheck
npm run build
```

Explicitly report the tests proving:

- ten external views use one manifest subprocess;
- manifest IDs and filenames are validated;
- legacy view calls share one decreasing deadline;
- local enqueue returns before work finishes;
- the scan POST returns while a deliberately blocked background job remains unfinished.

## Phase 6 — launch cleanly

Backend terminal:

```bash
cd apps/api
uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend terminal:

```bash
cd apps/web
npm run dev -- --port 3000
```

Check:

```bash
curl -s http://localhost:8000/healthz
curl -s http://localhost:3000/api/health
```

Local health must say `job_backend: local-thread`. If it says `inline`, stop: the stall-prone runtime
is still active or an old process is serving requests.

## Phase 7 — prove request/background separation

1. Register at least one reference through the UI.
2. Start a scan and measure the POST acceptance time separately from completion time.
3. The POST must return `202` with a scan ID in under 5 seconds for a normal local upload.
4. Poll that exact ID and record every distinct `creatorproof.scan_progress.v1` stage.
5. Confirm the UI displays a visible progress bar, plain label, percentage, elapsed seconds, and scan ID.
6. Confirm no Evidence Microscope is rendered until the scan is `COMPLETED`.
7. If live polling reaches three minutes, confirm it pauses and **Check again** resumes the same scan.
8. Confirm a slow/failed proof receipt cannot change a completed core scan to `FAILED`.

## Phase 8 — measure real latency

Run one warm-up, then at least three measured scans using the same representative image:

```bash
cd apps/api
uv run python -m scripts.benchmark_scan_latency /absolute/path/to/image.png \
  --api-url http://localhost:8000 \
  --api-key "$CREATORPROOF_DEV_API_KEY" \
  --catalog-id demo-catalog
```

If the key is not exported, load it through the normal local environment mechanism without printing it.
Report each run plus median and worst case. Do not average away an outlier.

For a GRIP-enabled result, inspect:

```text
evidence_packet.synthetic_origin.runtime.view_count
evidence_packet.synthetic_origin.runtime.provider_inference_modes
evidence_packet.synthetic_origin.runtime.provider_timings_ms
```

Required result: ten views when spatial crops are enabled, and the GRIP provider must report
`BATCHED_VIEWS`. Corroborate with process/log observation that one adapter process was launched for
the scan. A source test alone is not enough for the live claim.

## Phase 9 — semantic regression

Run the established exact/retouched-copy, hard-negative, visible-label, unrelated-AI, creator-style,
and no-detector cases. Compare v0.9 and v0.9.1 classifications and score inputs. Runtime changes must
not alter the thresholds or policy semantics. If a result changes, find the data/model/config cause;
do not tune the score to restore a desired screenshot.

## Phase 10 — browser audit

Use a real browser at the target viewport and capture:

1. queued/starting progress;
2. AI-use progress;
3. catalog-comparison progress;
4. completed case summary;
5. paused polling with **Check again**, using a controlled delayed test if needed;
6. narrow/mobile layout.

Confirm the progress card is readable, colourful, and more visually prominent than technical details.

## Required execution report

Create `V091_TARGET_MACHINE_EXECUTION_REPORT.md` containing:

- exact version/build/environment;
- sanitized queue and provider configuration;
- model artifact paths and SHA-256 values, never secrets;
- static/build/test results and exact test count;
- POST acceptance latency for every measured run;
- total runtime, median, worst case, and every stage transition;
- GRIP process count, batch view count, inference mode, and provider timing;
- OCR/provenance/retrieval/style/proof timing observations where available;
- browser screenshots and plain-language UX findings;
- semantic regression results;
- all failures, warnings, unavailable providers, and remaining blockers;
- one of: `SOURCE_VERIFIED`, `RUNTIME_READY`, `DEMO_READY`, or `BLOCKED`, with evidence.

Do not claim a production SLA or detection accuracy from these latency runs. Do not call the build
`DEMO_READY` unless the actual configured model artifacts completed the live end-to-end cases.

---

