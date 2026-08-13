# CreatorProof v0.6 validation record

Date: 9 August 2026.

## Verified in this build environment

- Python lint: `ruff check app tests scripts` passed.
- Python formatting: `ruff format --check app tests scripts` passed.
- Backend tests: **17/17 passed**.
- Frontend TypeScript: `npm run typecheck` passed.
- Next.js production build: `npm run build` passed.
- API/UI version identity: `0.6.0` in source manifests and visible UI markers.

New deterministic tests verify:

1. CSD+ readout emits raw pool cosine and CSLS while excluding self-similarity from anchor density.
2. The catalog diagnostic detects a negative discrimination gap.
3. A synthetic cross-content case using the reported signal pattern—learned style `0.819`, strong
   mark-making/texture, tile consistency `0.778`, and content control `0.453`—produces a high style-review
   result instead of being diluted into the copy index.
4. The transparent diagnostic fallback never triggers creator-attribution policy review.
5. Existing copy evidence, geometry fail-closed behavior, idempotency, authentication, and media behavior
   remain covered.

## Not verified here

- The external CSD runtime/weights were not bundled or downloaded in this workspace.
- No accuracy number was measured on a real creator-disjoint art dataset.
- The attached user screenshot was visually inspected and its reported metrics informed the regression,
  but copyrighted pixels were not copied into source fixtures or the distributable archive.
- IntroStyle, DiffSim, and ALADIN remain benchmark challengers, not claimed active providers.
- C2PA and blockchain anchoring remain provider boundaries; no live manifest or chain receipt was created.

## Required local learned-style acceptance

```bash
cd apps/api
uv sync --dev
uv pip install -r requirements-ai.txt
uv pip install -r requirements-style-experimental.txt
uv run --no-sync python scripts/fetch_sscd_model.py
uv run --no-sync python -m scripts.fetch_csd_runtime
```

If safe checkpoint loading fails, copy the SHA-256 printed by the fetcher into `.env`, enable the explicit
legacy-pickle flag, then run:

```bash
uv run --no-sync python -m scripts.check_ai
uv run --no-sync python -m scripts.check_style_ai --require-learned
uv run --no-sync python -m scripts.benchmark_style_retrieval \
  /absolute/path/to/creator_disjoint_style_manifest.json --require-learned
```

Promotion requires real held-out metrics, per-creator error analysis, difficult related-style negatives,
and a chosen customer-specific false-positive budget. A single visually convincing pair is a regression
case, not calibration data.
