# CreatorProof validation record

## v0.9.2 semantic-safety validation

Snapshot: 10 August 2026. Build: `0.9.2 / SEMANTIC-SAFETY-SCOPE-2026.08.10`.

Checks actually run in the handoff environment:

- `apps/api/.venv/bin/pytest`: **85 passed**.
- `apps/api/.venv/bin/ruff check app tests scripts`: passed.
- `apps/api/.venv/bin/ruff format --check app tests scripts`: passed.
- `apps/web/npm run typecheck`: passed.
- `apps/web/npm run build`: passed with Next.js 16.3.0.
- Coverage tests exercise complete, empty, partial, degraded, truncated, and failed states.
- API regressions prove empty scope cannot pass, payload-changing idempotency reuse returns `409`,
  asserted/revoked claims cannot authorize use, and disabled/informational/required origin modes have
  separate policy authority.
- Existing copy geometry, style, origin, proof, runtime, and non-blocking scan tests remain green.

Warnings retained for follow-up: Starlette's httpx compatibility path is deprecated in favor of
`httpx2`, and upstream `torch.jit.load` emits a deprecation warning. Neither warning is suppressed or
represented as fixed.

See `../V092_SEMANTIC_SAFETY_REPORT.md` for the detailed behavior matrix and remaining risks.

## Historical v0.4 validation record

Snapshot: 9 August 2026. Build: `0.4.0 / DUAL-LANE-2026.08.09`.

This is a record of checks actually run in the handoff environment, not a production/SOTA claim.

## Passed in this environment

- `ruff check app tests scripts`: passed after v0.4 changes.
- `pytest -q`: **9/9 passed**.
- `npm run typecheck`: passed.
- `npm run build`: passed with Next.js 16.3.0.
- Exact/copy evidence tests still pass; style analysis did not alter copy decision semantics.
- Hard-negative copy test remains source-scoped (`NO_MATCH...` or `INCONCLUSIVE`) and keeps legal
  language out of the detector result.
- New style regression registers two works under the same creator, verifies they aggregate into one
  `LIMITED_PROFILE`, and verifies the independent style packet contains a 4x4 map with 16 candidate
  and 16 reference cells.
- Test runtime (where external CSD is intentionally absent) reports
  `diagnostic-style-signature-v1`, `style_available=true`, `style_learned=false`.
- Frontend compile verifies the new dual-reference props and all four v0.4 microscope modes.

## What was not measured here

- **CSD style accuracy was not measured.** The multi-gigabyte external checkpoint/runtime was not
  downloaded in this environment. The adapter, setup/check scripts, health state, profile aggregation,
  fallback, evidence schema, and benchmark tool are implemented.
- No ALADIN/StyleDecoupler model tournament was executed.
- No customer/artist-specific style threshold was calibrated.
- No Docker Compose startup was run in this validation pass.
- C2PA/EAS remain provider boundaries, not active provenance/blockchain transactions.

## Required local learned-style acceptance

```bash
cd apps/api
uv pip install -r requirements-style-experimental.txt
uv run --no-sync python -m scripts.fetch_csd_runtime
uv run --no-sync python -m scripts.check_style_ai --require-learned
uv run --no-sync python -m scripts.benchmark_style_retrieval \
  path/to/your_style_manifest.json --require-learned
```

Require the check to say `learned: true`. Record the exact repository commit/checkpoint SHA printed
by the fetch script. Then evaluate different-content positives and difficult related-style negatives;
do not use transformed copies as a substitute for the style benchmark.

## Truth boundary

The included style fallback is an explainable engineering baseline, not proof that the CSD route is
effective. Conversely, a strong CSD/ALADIN result on a local benchmark is corpus-specific and still
does not turn style similarity into proof of copying, model training provenance, or infringement.
