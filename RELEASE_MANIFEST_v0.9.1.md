# CreatorProof v0.9.1 — release manifest

Build: `0.9.1 / BATCHED-NONBLOCKING-SCAN-2026.08.09`

## Scope

This release corrects the v0.9 scan-stall architecture. It does not tune detection thresholds,
calibration, match fusion, style fusion, or product policy.

## Key changed files

- `apps/api/app/services/jobs.py` — non-blocking local queue lifecycle.
- `apps/api/app/services/evidence.py` — atomic claim, persisted progress, deferred proof.
- `apps/api/app/providers/synthetic_detection.py` — manifest batch and shared legacy deadline.
- `apps/api/scripts/clipdet_json_adapter.py` — one official multi-row GRIP run.
- `apps/api/app/providers/visible_markers.py` — whole-OCR-stage deadline.
- `apps/api/scripts/benchmark_scan_latency.py` — real target-machine timing harness.
- `apps/web/app/page.tsx` — bounded polling, elapsed progress, recoverable continuation.
- `apps/web/app/api/scans/**` — finite upstream acceptance/poll timeouts.
- `apps/web/app/globals.css` — visible, plain-language progress card.
- `.env.example` — local queue default and `{manifest}` GRIP configuration.
- `tests/test_scan_runtime.py` and `tests/test_synthetic_adapter.py` — latency regressions.
- `V091_PACKAGING_VALIDATION_REPORT.md` — checks completed and explicit non-claims.

## Excluded from the archive

- model weights and external repositories;
- `.env` and `.env.local` secrets;
- databases, object data, logs, caches, `.venv`, `node_modules`, and Next build output;
- blockchain credentials.

## Promotion statement

Source verification can establish that batching and non-blocking job execution are implemented.
`DEMO_READY` additionally requires a target-machine run with the actual model artifacts and the
acceptance gates in `V091_SCAN_STALL_CORRECTION_REPORT.md`.
