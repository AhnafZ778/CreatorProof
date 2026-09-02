# CreatorProof v0.9.0 — release manifest

Build: `0.9.0 / PLAIN-SCORE-WATERMARK-2026.08.09`

## Primary v0.9 documents

- `MASTER_EXECUTION_PROMPT_v0.9.md` — installation, model activation, OCR validation, calibration,
  E2E, browser, proof, and reporting instructions.
- `V09_EXECUTION_REPORT.md` — checks actually run and remaining empirical blockers.
- `docs/V09_ORIGIN_SCORE_AND_PRODUCT_UI.md` — architecture, score math, decision semantics,
  plain-language UI, research map, and validation protocol.

## Backend implementation

- `apps/api/app/providers/visible_markers.py`
  - local Tesseract provider;
  - full-image plus corner views;
  - sparse and block OCR layouts;
  - explicit AI-use phrase matching;
  - normalized label localization;
  - fail-neutral semantics.
- `apps/api/app/providers/contracts.py`
  - structured visible-marker evidence contract.
- `apps/api/app/services/synthetic_analysis.py`
  - visible-label and learned-family fusion;
  - AI signal and evidence quality scorecard;
  - v3 origin schema;
  - plain result and next action.
- `apps/api/app/services/evidence.py`
  - visible-label execution independent of catalog search;
  - v0.9 evidence bundle;
  - no-match-safe joint case summary;
  - unresolved-origin product review overlay.
- `apps/api/app/core/config.py`, `apps/api/app/container.py`, `.env.example`
  - configurable marker runtime and dependency wiring.
- `apps/api/app/api/routes/health.py`, `apps/api/app/schemas.py`
  - visible-label readiness in health output.

## Frontend implementation

- `apps/web/app/components/EvidenceMicroscope.tsx`
  - bottom line and action first;
  - AI signal and evidence quality scorecard;
  - plain factor explanations;
  - localized visible-label overlay;
  - four primary views;
  - technical evidence collapsed.
- `apps/web/app/globals.css`
  - larger responsive type and controls;
  - stronger lane colors and hierarchy;
  - scorecard, marker, disclosure, and mobile styling.
- `apps/web/app/page.tsx`, `apps/web/app/layout.tsx`, package files
  - v0.9 identity, simpler wording, and collapsed readiness ledger.

## Tests

- `tests/test_visible_markers.py`
  - mocked phrase/localization checks;
  - unrelated-text negative;
  - unavailable-provider neutral behavior;
  - real Tesseract inference regression.
- `tests/test_synthetic_origin.py`
  - marker-only review;
  - no-label neutrality;
  - scorecard contract.
- `tests/test_case_summary.py`
  - no-match cannot suppress origin;
  - quiet result does not claim human origin.
- `tests/test_style_evidence.py`, `tests/test_scan_flow.py`
  - unresolved-origin policy review and end-to-end policy consistency.
- `tests/test_health.py`
  - v0.9 build, ensemble v3, and marker health contract.

## Intentionally excluded from the distributable archive

- `.env`, `.env.local`, API/RPC/OpenRouter keys, and signer secrets;
- model weights, Git-LFS third-party artifacts, and `vendor/`;
- `.venv`, `node_modules`, `.next`, caches, and compiled artifacts;
- databases, uploaded works, evidence outputs, user images, and benchmark datasets.

## Promotion state

`SOURCE_VERIFIED`. Follow `MASTER_EXECUTION_PROMPT_v0.9.md` for target-machine activation and higher
evidence-backed promotion.
