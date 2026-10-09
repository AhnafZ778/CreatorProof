# CreatorProof Phase 1 Repository Audit

## Scope

Phase 1 is backend-only. Existing frontend changes are treated as the working-tree baseline and are not modified by this phase.

## Existing capabilities

- Tenant-scoped works, scans, uploads, storage, API-key authentication, scopes, audit events, and row-level-security support.
- Rights entities: parties, creator profiles, claims, licenses, rights events, and immutable organization policy versions.
- Scan evidence packets covering copy, origin, provenance, style/profile, source coverage, integrity, and policy decisions.
- Read-only C2PA inspection through the configured official `c2patool` provider.
- Signed evidence statements, transparency leaves/checkpoints, integrity events, and optional blockchain anchoring.
- Human review cases and review events.
- Marketplace observation and reviewable takedown drafts.
- Server-side AIand configuration used for draft generation.
- SQLite development and PostgreSQL migration paths, Redis/local queues, and private object storage adapters.

## Phase 1 gaps

- No versioned rights-policy/passport projection and machine-readable exports.
- Provenance is present in evidence packets but lacks durable normalized records and inspection APIs.
- Evidence is packet-only; normalized signal, coverage, and final matrix rows are missing.
- No append-only human contribution ledger.
- AIand output is not yet a general structured investigation record with traceable human decisions.
- No public verification token model or unauthenticated redacted verification endpoint.
- Provider preflight, recursive redaction, bounded AI provider behavior, and Phase 1 documentation/tests are incomplete.

## Compatibility and known baseline issues

- Existing scan/evidence packet fields must remain backward compatible.
- Migration `0008_user_detection_notice_context.py` needs an idempotent index guard.
- The current model-bundle application revision is stale after existing backend changes; it must be regenerated after Phase 1 backend changes are final.
- Candidate media is deleted when retention is zero; Phase 1 must preserve that behavior.

## Frontend freeze

The pre-existing dirty frontend files and untracked frontend additions are recorded in `docs/phase1-frontend-baseline.json`. The baseline contains 105 source files and includes earlier UI work. `python3 scripts/phase1_frontend_guard.py` compares file membership and hashes. No Phase 1 files under `apps/web` may be added or edited; no commit or reset is needed to preserve the baseline.

## Existing tables and API extension map

| Existing abstraction | Phase 1 extension |
|---|---|
| Work, AssetVersion, Catalog/versions | Work tombstone, active-work filtering, contribution asset identity |
| Claim, License, RightsEvent | Reused contract/assertion evidence; per-work RightsPolicyVersion added for preferences |
| PolicyVersion / PolicyStore | Existing organization rules extended with deterministic preference and scope facts |
| Scan / ScanInputBinding / StageExecution | Additive declared-use context, persisted matrix finalization and failure paths |
| EvidenceStatement / IntegrityEvent / transparency | Reused packet commitments, signed rights events, and hash bindings |
| ReviewCase / ReviewEvent | Reused human review; investigation outputs retain original generated content |
| MarketplaceAsset / TakedownDraft | Existing discovery and drafts preserved; generated draft linked to investigation output |
| DeletionReceipt / local/S3 object store | Candidate expiry/retry, source deletion, explicit immutable-history scope |

Existing `/v1/works`, `/v1/scans`, `/v1/rights`, `/v1/policies`, `/v1/review`, `/v1/admin`, marketplace, proof, and authenticated media APIs remain. New passport/export/ledger/token routes live in `routes/passports.py`; provenance/matrix routes in `routes/phase1.py`; assistant routes in `routes/investigations.py`; only `/verify/{token}` is public.

## Files changed by Phase 1

- API models/db/Alembic migrations: additive entities, tenant constraints, immutable guards, SQLite FKs and PostgreSQL parity.
- API routes: passports, phase1, investigations; additive integration in scans/works/rights/Admin and main registration.
- Services/providers: rights_passport, policy_store, evidence_matrix, provenance_records, provenance adapter, aiand, retention, safe_http, scan_runner, evidence and active-work retrieval filters.
- Runtime: config, middleware, observability, container/worker, Compose and model-bundle source revision after finalization.
- Tests/scripts: `test_phase1_*`, backend/preflight/benchmark/PostgreSQL tooling, and frontend hash guard.
- Documentation: all required Phase 1 artifacts, setup links and final verification report.

## Provider evidence and availability

The repository already integrates Sightengine, AI & Inference, Unsplash/Pixabay, SSCD, synthetic-origin/style routers, optional Redis/S3/PostgreSQL, and official c2patool. Locally configured credentials are not reproduced here. The preflight has confirmed the installed C2PA binary identity; external providers remain configured-but-not-live-checked until an explicit successful health check. The offline benchmark deliberately disables cloud origin, provenance, and creator-profile checks and records those lanes unavailable. Optional connector failure must not disable user-submitted scanning. Signing, automatic notice delivery, managed services, global web search and training infrastructure are outside Phase 1.

## Provider status policy

Provider configuration is not treated as provider health. The Phase 1 preflight distinguishes configured, live-verified, unavailable, and deferred providers and never prints secret values.
