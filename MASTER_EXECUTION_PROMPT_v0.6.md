# CreatorProof v0.6.0 — master agentic execution prompt

Paste everything below into an agentic IDE opened at the extracted `creatorproof` repository root.

---

You are the execution, verification, and calibration engineer for **CreatorProof v0.6.0 / CSD-PLUS-STYLE-EVIDENCE-2026.08.09**.

Your task is to install the complete local application, activate its real local AI providers where the
machine supports them, run every quality gate, verify copy and style lanes separately, exercise the CSD+
catalog readout, and return a falsifiable report. Do not edit thresholds to make one example pass. Do not
describe a provider as active unless health plus real inference prove it. Do not call any score a legal
infringement probability.

## 1. Confirm the checkout

Read these files before executing anything:

- `BUILD_INFO.md`
- `README.md`
- `docs/V06_STYLE_EVIDENCE_MATH.md`
- `docs/V06_RESEARCH_AND_MODEL_TOURNAMENT.md`
- `docs/V06_VALIDATION.md`

Required identity:

- API and frontend version: `0.6.0`
- build signature: `CSD-PLUS-STYLE-EVIDENCE-2026.08.09`
- style packet schema: `creatorproof.style_evidence.v2`

Stop and report a version mismatch if the manifests disagree. Work only inside this checkout. Preserve
user files and do not kill unrelated processes.

## 2. Record the toolchain

```bash
python3 --version
uv --version
node --version
npm --version
```

Expected: Python 3.12+, working `uv`, Node 20.9+, and npm. If `uv` cannot write its default cache, set a
project-specific cache such as `UV_CACHE_DIR=/tmp/creatorproof-uv-cache`; do not change the user's home.

## 3. Install and verify the backend

```bash
cd apps/api
uv sync --dev
uv pip install -r requirements-ai.txt
uv run --no-sync python scripts/fetch_sscd_model.py
uv run --no-sync python -m scripts.check_ai
```

SSCD acceptance:

- provider is `sscd-disc-mixup-torchscript`;
- `available=true`;
- output dimension is 512;
- L2 norm is approximately 1;
- repeated inference similarity is approximately 1.

If the official SSCD file already exists, do not overwrite it blindly. Verify the existing artifact and
record its SHA-256.

Run all backend gates:

```bash
uv run ruff check app tests scripts
uv run ruff format --check app tests scripts
uv run pytest -q
```

All tests must pass. The expected shipped suite is at least **15 tests** and includes CSD+ readout,
negative discrimination-gap, cross-content corroborated style fusion, diagnostic fallback safety,
copy-fusion, geometry, authentication, and scan-flow regressions.

## 4. Activate learned creator-style inference

The transparent fallback is useful only for explanation. The requested style-attribution experiment
requires learned CSD:

```bash
uv pip install -r requirements-style-experimental.txt
uv run --no-sync python -m scripts.fetch_csd_runtime
```

Record both the CSD repository commit and checkpoint SHA-256 printed by the fetcher.

PyTorch 2.6+ may reject the legacy checkpoint in safe `weights_only` mode. Do not bypass this silently.
If and only if the checkpoint came from the recorded fetch and its digest was measured, put these exact
values in `apps/api/.env`:

```dotenv
CREATORPROOF_STYLE_ALLOW_LEGACY_PICKLE=true
CREATORPROOF_STYLE_CSD_EXPECTED_SHA256=<THE_64_CHARACTER_SHA256_PRINTED_BY_THE_FETCHER>
```

Then run:

```bash
uv run --no-sync python -m scripts.check_style_ai --require-learned
```

Acceptance:

- `provider=csd-vit-l-experimental`;
- `learned=true`;
- output is finite, unit normalized, and repeatable;
- no fallback reason is present;
- exact source commit and weight digest are in the report.

If this fails, retain the diagnostic fallback and report learned style unavailable. Never modify tests to
accept a fallback while claiming CSD is active.

## 5. Configure the frontend safely

```bash
cd ../web
npm install
npm run typecheck
npm run build
```

Both gates must pass. Configure `apps/web/.env.local` without exposing secrets to browser code:

```dotenv
CREATORPROOF_API_URL=http://localhost:8001
CREATORPROOF_DEV_API_KEY=change-me-before-sharing
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
OPENROUTER_SITE_URL=http://localhost:3001
```

OpenRouter is optional and explains recorded metrics only. An empty key must not affect detection.

## 6. Start the application

Use available ports; the following are recommended.

Backend terminal:

```bash
cd apps/api
uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Frontend terminal:

```bash
cd apps/web
CREATORPROOF_API_URL=http://localhost:8001 npm run dev -- --port 3001
```

Health checks:

```bash
curl -s http://localhost:8001/healthz
curl -s http://localhost:3001/api/health
```

Both must report `0.6.0`. Record SSCD and style provider, device, learned state, and fallback reason.

## 7. Browser acceptance

Open `http://localhost:3001` and verify with screenshots:

1. the top bar and case header display `v0.6.0`;
2. the page uses the available desktop width without huge dead margins;
3. Register → Scan → Explore remains obvious and keyboard navigable;
4. every completed case shows separate **Copy evidence** and **Style resemblance** cards;
5. one score cannot visually masquerade as the other;
6. Copy regions emit annotations only after geometry validation;
7. Creator style displays raw CSD pool cosine, CSD+ CSLS rank score, SSCD content control,
   style-content gap, discrimination gap, catalog rank, and profile size;
8. Style map contains no copy connector or geometric implication;
9. style action states `Human review recommended` only when the learned decision says so;
10. every percentage says evidence/index rather than probability or infringement.

Check responsive layouts near 1440px, 1024px, and 390px widths. Report clipping, overlap, unreadable text,
or inaccessible controls rather than hiding them.

## 8. Build a legitimate style evaluation catalog

Use images you are authorized to test. Do not add the user's attached example or third-party copyrighted
art to source control.

Minimum meaningful catalog:

- at least three creators;
- preferably 10–20 representative anchors per creator;
- at least three works per creator for UI profile reliability;
- creators with nearby styles/traditions, not only easy unrelated negatives;
- held-out queries with different subject/content from their creator anchors;
- same-subject/different-style, same-palette/different-mark-making, and same-movement/different-creator
  negatives.

Avoid image-to-image retouches as the main style benchmark; those belong to the copy benchmark.

Style manifest format:

```json
{
  "references": [
    {"path": "references/creator-a-01.png", "creator": "creator-a"},
    {"path": "references/creator-a-02.png", "creator": "creator-a"},
    {"path": "references/creator-b-01.png", "creator": "creator-b"}
  ],
  "queries": [
    {"path": "queries/a-heldout-01.png", "expected_creator": "creator-a"},
    {"path": "queries/b-heldout-01.png", "expected_creator": "creator-b"}
  ]
}
```

Run:

```bash
cd apps/api
uv run --no-sync python -m scripts.benchmark_style_retrieval \
  /absolute/path/to/style_manifest.json --require-learned --k 5 --csls-k 15
```

Report raw pool cosine and CSD+ CSLS separately:

- top-1 creator accuracy;
- recall@5;
- pair verification ROC-AUC;
- dataset-specific EER and threshold;
- negative discrimination-gap count;
- every query where raw and CSLS disagree;
- per-creator failures.

Do not publish the EER threshold as universal. It belongs only to that manifest.

## 9. Verify the reported cross-content regression

The shipped deterministic regression represents this signal pattern:

- learned style similarity around `0.819`;
- strong mark-making/texture diagnostics;
- bidirectional tile consistency around `0.778`;
- SSCD content/copy similarity around `0.453`;
- multiple creator anchors and positive catalog discrimination.

Require the regression to produce:

- style evidence index in the strong band (the shipped test expects approximately `0.82–0.86`);
- style tier `HIGH` or stricter;
- `review_recommended=true`;
- `STYLE_EXCEEDS_CONTENT_CONTROL`;
- no automatic copy `MATCH_FOUND` caused by style.

This is a fusion consistency test, not proof that the original screenshot is legally infringing.

## 10. Mandatory end-to-end cases

Run and record these cases in the UI and API:

### A. Near-copy / retouch

Use a crop, perspective change, recompression, and colour retouch of a registered reference. Require the
correct source to become verification rank 1 when robust geometry/structure support it. Copy evidence can
be high; style evidence may also be high but is not needed for the copy decision.

### B. Different-content / same-creator style

Use a held-out different-subject positive. Geometry should normally reject without annotations. Learned
style should rank the correct creator and may recommend review. `match_status` must not become
`MATCH_FOUND` from style alone.

### C. Same-movement hard negative

Use a work by a nearby but different creator. Require the system to show the competitor, discrimination
gap, and CSLS result. Record any false style review; do not tune it away on the same data.

### D. Unrelated hard negative

The catalog still has a nearest item, but copy annotations must remain empty after geometry rejection.
Learned style should not recommend review unless independently supported.

### E. Diagnostic-only fallback

Temporarily configure `CREATORPROOF_STYLE_PROVIDER=diagnostic`. Confirm the tier becomes `DIAGNOSTIC` and
cannot trigger creator-attribution policy review. Restore the original setting afterward.

## 11. Copy benchmark

Run the existing copy-fusion benchmark on a held-out pair manifest:

```bash
uv run --no-sync python -m scripts.benchmark_copy_fusion \
  /absolute/path/to/copy_manifest.json
```

Report precision, recall, false-positive rate, review rate, ROC-AUC, and failure cases. A three-case toy
dataset is a smoke test, not evidence of production accuracy.

## 12. Policy invariants

Verify directly in JSON:

- style never changes copy `match_status`;
- learned style review can change a no-copy `PASS_BY_POLICY` to `REVIEW`;
- reason codes include `STYLE_RESEMBLANCE_REVIEW_RECOMMENDED` and
  `STYLE_REVIEW_IS_NOT_COPY_OR_INFRINGEMENT_FINDING`;
- diagnostic fallback cannot escalate policy;
- OpenRouter cannot change any metric or decision;
- C2PA/blockchain status remains not configured unless a real receipt proves otherwise.

## 13. Final report format

Return one report containing:

1. tool and OS versions;
2. exact checkout version/build identity;
3. backend/frontend commands and ports;
4. health JSON and provider/device state;
5. SSCD digest and inference check;
6. CSD source commit, checkpoint digest, safe/legacy loader state, and inference check;
7. backend lint/format/test counts;
8. frontend typecheck/build results;
9. browser screenshots and responsive findings;
10. all five end-to-end case outcomes with copy and style decisions separated;
11. raw-vs-CSLS style benchmark table and per-creator failures;
12. copy benchmark results;
13. policy-invariant checks;
14. unresolved limitations and the next highest-value experiment.

Never use `perfect`, `bulletproof`, `100% accurate`, `SOTA`, `copied by the model`, or `legally
infringing` unless an appropriately designed independent evaluation or legal process actually supports
that exact claim. The correct product language is **catalog-scoped, auditable resemblance evidence and
human-review routing**.

---
