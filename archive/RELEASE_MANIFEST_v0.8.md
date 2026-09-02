# CreatorProof v0.8.0 — release manifest

Build: `0.8.0 / CLEAR-ORIGIN-ENSEMBLE-2026.08.09`

## Primary v0.8 files

- `MASTER_EXECUTION_PROMPT_v0.8.md` — target-machine installation, model activation, calibration,
  E2E, browser, blockchain, and reporting instructions.
- `V08_EXECUTION_REPORT.md` — honest packaging checks and remaining runtime blockers.
- `docs/V08_ORIGIN_DETECTION_AND_UI.md` — root-cause audit, architecture, decision math, model
  strategy, UI contract, and validation rules.

## Detection implementation

- `apps/api/app/providers/synthetic_detection.py`
  - official Community Forensics transform;
  - evidence-family metadata;
  - calibration-safe external adapters;
  - provider/family health ledger.
- `apps/api/app/services/synthetic_analysis.py`
  - delivery robustness views;
  - multi-crop consensus;
  - family-level fusion;
  - low-resolution/instability/disagreement/coverage abstentions;
  - plain-language presentation contract.
- `apps/api/scripts/clipdet_json_adapter.py`
  - official GRIP repository adapter using upstream `soft_or_prob` fusion;
  - optional isolated Python runtime;
  - raw-score semantics preserved.
- `apps/api/scripts/collect_synthetic_calibration_scores.py`
  - provider/model-version score collection for an authorized calibration partition.
- `apps/api/scripts/calibrate_synthetic_scores.py`
  - support-gated provider-specific Platt calibration.
- `apps/api/scripts/benchmark_synthetic_detection.py`
  - generator/source groups, selective-risk metrics, confidence interval, and promotion gates.
- `apps/api/scripts/check_synthetic_ai.py`
  - activation, evidence family, score semantics, repeatability, and calibration report.

## Health and evidence contract

- `apps/api/app/__init__.py` — v0.8 version and build signature.
- `apps/api/app/schemas.py` — health family ledger.
- `apps/api/app/api/routes/health.py` — build signature and active evidence families.
- `apps/api/app/providers/contracts.py` — explicit evidence family and score semantics.
- `apps/api/app/services/evidence.py` — v2 origin packet and plain fallback presentation.
- `apps/api/app/core/config.py` — spatial/family settings.
- `.env.example` — v0.8 settings and official GRIP adapter example.

## UI implementation

- `apps/web/app/components/EvidenceMicroscope.tsx`
  - bottom-line-first result;
  - three clickable plain-language lanes;
  - origin conclusion/next action/three facts;
  - technical evidence collapsed by default;
  - no raw uncalibrated origin percentages.
- `apps/web/app/globals.css`
  - clearer color hierarchy, lane states, focus, compact responsive layout, and technical
    disclosure styling.
- `apps/web/app/page.tsx`, `apps/web/app/layout.tsx`, `apps/web/package.json`,
  `apps/web/package-lock.json` — v0.8 identity.

## Tests

- `apps/api/tests/test_synthetic_origin.py` — corrected decision and preprocessing contract.
- `apps/api/tests/test_synthetic_adapter.py` — LLR mapping and official fused-output regression.
- `apps/api/tests/test_health.py` — v0.8 build/provider identity.

## Intentionally excluded from the distributable archive

- `.env`, `.env.local`, API keys, RPC credentials, and private keys;
- model/checkpoint weights and Git-LFS third-party artifacts;
- `vendor/`, virtual environments, `node_modules/`, `.next/`, and tool caches;
- SQLite databases, uploaded works, generated evidence, screenshots, and benchmark corpora;
- compiled Python/TypeScript artifacts and OS metadata.

## Promotion state

`SOURCE_VERIFIED`. Follow `MASTER_EXECUTION_PROMPT_v0.8.md` to reach a higher evidence-backed state.

