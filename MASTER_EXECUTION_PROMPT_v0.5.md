# CreatorProof v0.5.1 — master agentic execution prompt

Paste everything below into an agentic IDE while the IDE is opened at the extracted `creatorproof`
repository root.

---

You are the execution and verification engineer for **CreatorProof v0.5.1 / NAVIGATION-SPECTRUM-2026.08.09**.
Do not redesign the detector or change thresholds merely to make a single demo pass. First reproduce
the shipped acceptance checks exactly, then report evidence. Never claim a provider is active unless
runtime health and a real inference check prove it.

## Goal

Bring up the complete local app, activate SSCD copy retrieval, verify v0.5 corroborated copy fusion,
verify the side-by-side Evidence Microscope, and report all failures honestly. The style lane is separate:
use its transparent fallback by default or activate CSD only when its exact external runtime passes its
checker. OpenRouter is optional and must never affect detection.

## 1. Identify this checkout

From the repository root inspect:

- `BUILD_INFO.md`
- `README.md`
- `docs/V05_DETECTION_MATH.md`
- `docs/V05_RESEARCH_AND_REPO_MAP.md`

Required identity is `0.5.1` and `NAVIGATION-SPECTRUM-2026.08.09`. Stop and report a version mismatch
if source files disagree.

## 2. Toolchain

Record:

```bash
python3 --version
uv --version
node --version
npm --version
```

Expected family: Python 3.12+, a working `uv`, Node 20.9+, and npm. Do not silently use a different
project directory if a command fails.

## 3. Backend dependencies and SSCD

```bash
cd apps/api
uv sync --dev
uv pip install -r requirements-ai.txt
uv run --no-sync python scripts/fetch_sscd_model.py
uv run --no-sync python -m scripts.check_ai
```

`check_ai` must report the SSCD TorchScript provider available, a 512-dimensional embedding,
approximately unit L2 norm, and repeatable inference. If it does not, detection can still run with the
declared fallback, but you must not describe the run as SSCD-active.

Run backend gates:

```bash
uv run ruff check app tests scripts
uv run ruff format --check app tests scripts
uv run pytest -q
```

All tests must pass. The v0.5 suite includes a deterministic regression where a perspective/colour
retouch receives simulated SSCD 0.72 but strong geometry + aligned structure must still produce
`VERIFIED_NEAR_DUPLICATE`.

## 4. Optional learned style provider

The app works without this step. If the machine can support the experiment:

```bash
uv pip install -r requirements-style-experimental.txt
uv run --no-sync python -m scripts.fetch_csd_runtime
uv run --no-sync python -m scripts.check_style_ai --require-learned
```

Do not suppress CSD's upstream checkpoint warning and do not call raw style cosine a probability. If this
step fails, keep the explicit diagnostic fallback and continue copy-lane acceptance.

## 5. Frontend dependencies and gates

In another terminal:

```bash
cd apps/web
npm install
npm run typecheck
npm run build
```

Both must pass.

`apps/web/.env.local` must contain a backend URL matching the port you will actually run. It may also
contain:

```dotenv
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
OPENROUTER_SITE_URL=http://localhost:3001
```

An empty OpenRouter key is valid. The explainer should then be disabled/fallback-visible; copy and style
measurement must be unaffected.

## 6. Start the app

Choose free ports. If using the ports from earlier CreatorProof demos:

Backend:

```bash
cd apps/api
uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Frontend (ensure `CREATORPROOF_API_URL` resolves to that backend through the server-side proxy):

```bash
cd apps/web
CREATORPROOF_API_URL=http://localhost:8001 npm run dev -- -p 3001
```

Check:

```bash
curl -s http://localhost:8001/healthz
curl -s http://localhost:3001/api/health
```

Both responses must identify API `0.5.1`; backend health must expose the actual copy/style provider state.

## 7. Browser/UI acceptance

Open `http://localhost:3001`. Verify visually:

1. status bar says `CreatorProof v0.5.1`;
2. headline is `See what matches. Understand why.`;
3. desktop content uses the available width instead of a narrow centered 1120px column;
4. the Register → Scan → Explore workflow strip is visible and navigable;
5. register and scan forms are visually distinct and work;
6. side-by-side candidate/reference images render at verification rank #1;
7. evidence ledger shows SSCD, pHash, geometry, aligned structure, and style as separate signals;
8. the colour-coded mode navigator exposes Case summary, Copy regions, Aligned structure, Creator style,
   and Style map with plain-language descriptions;
9. local feature pairs are numbered on both images, and only the inspected pair receives a connector;
10. no raw geometry-aligned pixel-difference heatmap is presented as proof;
11. rejected geometry shows no invented local annotations.

## 8. Mandatory multi-reference behavior

Register at least three visually different references in one catalog. Keep the test images under your own
temporary test directory; do not modify shipped source fixtures.

Positive case:

- choose reference A;
- make a transformed query using resize/recompression plus perspective and colour/contrast change;
- scan the transformed query;
- require the true source to become **verification rank #1** even if its original SSCD retrieval rank was
  not #1;
- require `MATCH_FOUND` when corroboration gates pass;
- inspect the Evidence Packet: `fusion.match_supported=true`, validated geometry, aligned structure
  available, and a non-probabilistic evidence index.

Hard-negative case:

- use a genuinely unrelated image;
- nearest-neighbour retrieval is expected because every non-empty corpus has a nearest item;
- require `fusion.match_supported=false` unless robust local evidence genuinely verifies;
- if geometry rejects, require zero exposed correspondences and zero verified support regions.

High-global/no-geometry case:

- confirm a high global similarity signal alone never becomes `MATCH_FOUND`; it may become
  `REVIEW_CANDIDATE`.

## 9. The 0.72 regression you must understand

v0.4 had a brittle rule: geometry + SSCD had to clear a single 0.75 SSCD gate. v0.5 does not simply lower
that threshold. It corroborates four families and uses explicit decision paths. A pair with SSCD about
0.72 can legitimately become a high-evidence match when robust geometry and aligned structure are very
strong. Read the exact equations and prototype gates in `docs/V05_DETECTION_MATH.md`.

Do not force every 0.72 pair to match. A 0.72 SSCD pair without local/structural corroboration should not
receive the same decision.

## 10. Benchmark harness

For any labeled pair dataset, create a JSON manifest outside source with entries like:

```json
{
  "cases": [
    {"id": "positive-1", "query": "q/a.jpg", "reference": "r/a.jpg", "label": true},
    {"id": "negative-1", "query": "q/x.jpg", "reference": "r/a.jpg", "label": false}
  ]
}
```

Then from `apps/api` run:

```bash
uv run --no-sync python -m scripts.benchmark_copy_fusion /absolute/path/to/manifest.json
```

Report confusion counts, recall, precision, false-positive rate, review rate, evidence-index ROC-AUC, and
failure examples. Do not publish an “accuracy” claim from a tiny synthetic corpus.

## 11. Style acceptance

Register at least three representative works with the identical Creator / style profile name and at least
two other creator profiles. Use a held-out image with different content/subject matter when testing style.

Verify:

- copy geometry may correctly reject a cross-content style example;
- style ranking still returns a creator profile independently;
- the profile reports centroid cosine, robust top-member statistic, within-profile cohesion, and a
  catalog-relative z-score only when enough profiles exist;
- style never changes copy `MATCH_FOUND` by itself;
- the style field is labelled diagnostic rather than pixel correspondence.

## 12. What to report

Return one execution report with:

- exact runtime/tool versions;
- API/frontend ports and health response;
- SSCD provider/device/dimensions;
- style provider and whether learned or fallback;
- backend test/lint/format result;
- frontend typecheck/build result;
- positive multi-reference result including both retrieval and verification rank;
- hard-negative result;
- 0.72 regression result;
- annotation/UI visual audit;
- benchmark statistics if a real labeled manifest was provided;
- C2PA/blockchain status stated honestly (provider-boundary/not-active unless a real integration and
  transaction/manifest receipt prove otherwise);
- every remaining limitation.

Never write `100% accurate`, `bulletproof`, `SOTA` or `infringing` merely because the demo passes. Use
`MATCH_FOUND`, `VERIFIED_NEAR_DUPLICATE`, `REVIEW_CANDIDATE`, and the exact provider/calibration state.

---
