# CreatorProof Phase 1: detailed implementation plan

## Scope and product rules

Extend the existing Python backend, database, evidence infrastructure, workers, security, tests, evaluation fixtures, and documentation. Do not change any file under `apps/web`. Preserve the existing dirty frontend as the starting baseline, including untracked source files, rather than resetting prior work. Keep legacy scan responses and evidence enum values compatible; new routes and fields must be additive.

Keep visual reuse, AI origin, creator resemblance, provenance, and permission separate. Similarity does not prove infringement; absent provenance does not establish human authorship; self-declaration does not independently verify ownership; style is not identity; a hash is not ownership; a match does not authorize a notice. Legal conclusions remain outside automated evaluation.

No automatic notice delivery, public-chain deployment, global reverse-image search, marketplace partner integration, custom model training, or frontend work is required.

## Stage 1 — Audit and access inventory

Read README, MODELS, the setup guide, Admin operations, evidence microscope, connector, CopyFlag philosophy, and blockchain documentation. Trace registration, user scans, monitor detection, review, notice drafting, proof generation, queues, storage, and deletion through their routes/services/models/tests.

Inventory existing environment variable names and presence without printing values. Identify local SQLite/queue/storage defaults and optional PostgreSQL, Redis, S3, Sightengine, AI & Inference, Unsplash, and Pixabay. Record configuration separately from successful live health checks.

Deliver `PHASE1_REPOSITORY_AUDIT.md`, `PHASE1_ACCESS_CHECKLIST.md`, and this plan before implementation. Capture a frontend hash baseline with `scripts/phase1_frontend_guard.py`. Identify the existing abstraction for each new feature; do not create another source of truth for contracts, organization rules, or signed packets.

**Completion gate:** the audit maps existing capabilities, gaps, tables, APIs, providers, and changed files; missing optional credentials do not block local work.

## Stage 2 — Database foundation

Reuse Work, AssetVersion, Scan, ScanInputBinding, Claim, License, RightsEvent, PolicyVersion, review cases, signed statements, audit records, and transparency records. Add only the missing persistent projections:

| Entity | Purpose and lifecycle |
|---|---|
| rights_policy_versions | Immutable per-work preference history, separate from contracts and organization policy |
| provenance_records / provenance_ingredients | Safe immutable inspection history for works and scans |
| evidence_matrices / evidence_signals / evidence_coverages | Finalized lane projections and numbered append-only corrections |
| contribution_events | Ordered append-only factual creation chain |
| investigation_runs / investigation_outputs | Operational run state, immutable generated content, one explicit reviewer transition |
| public_verification_tokens | Hashed random bearer tokens with scope, expiry, and revocation |

Use tenant IDs, composite same-tenant foreign keys, version/sequence uniqueness, bounded fields, date/enum constraints, and read indexes. Serialize appends against the parent and return predictable conflict responses. Enable SQLite foreign keys. Install forced PostgreSQL RLS and require a runtime role separate from the migration owner. Protect immutable data through ORM guards and database triggers in both SQLite and PostgreSQL; permit only documented operational projection transitions, including the first investigation-review transition.

Add migration/adoption checks for empty databases, legacy revisions, and existing create_all databases. Check SQLite batch alterations, idempotent indexes, migration revision-length storage, defaults, and schema drift. Reference deletion must retain documented tombstones when immutable history exists, while removing media and active access.

**Completion gate:** upgrade/adoption checks pass, schema drift is absent, forbidden updates and cross-tenant references fail, SQLite startup works, and actual PostgreSQL runtime/RLS behavior is tested when available.

## Stage 3 — AI Rights Passport

Create typed input and immutable per-work versions over existing rights abstractions. Implement all eleven requested permission fields with ALLOW, DENY, LICENSE_REQUIRED, REVIEW, UNKNOWN, and NOT_APPLICABLE. Omitted preferences remain UNKNOWN. New registrations receive an all-UNKNOWN version 1 with a system-baseline source and no invented consent or creator assertion; the first explicit declaration becomes version 2. Backfill only active historical works that lack a policy. This neutral baseline cannot override an otherwise valid scoped license.

Store creator linkage, effective dates, attribution, license requirements/contact/optional fee, geography, platform/model allow/deny lists, consent and revocation history, notes, assertion status, and corroborating references. Validate all referenced records in the same tenant. Submitted text cannot independently verify ownership or create a contract.

Add authenticated create/read/history routes using `/v1` conventions. Changes, corrections, and revocations append versions and rights/audit events; canonical digests bind content. Represent creator assertions, corroboration, licenses, platform rules, organization rules, and legal conclusions separately.

**Completion gate:** all permission values, invalid input, version conflicts, expiry, future dates, revocation, geography, and tenant isolation are tested.

## Stage 4 — Machine-readable preference exports

Add authenticated JSON policy, human-readable statement, ai.txt, TDM policy, AI Preferences, and unsigned C2PA usage-assertion exports. Include version, digest, state, asset identifier, and optional verification URL.

Check the primary references before fixing adapters: [Spawning ai.txt](https://site.spawning.ai/spawning-ai-txt), [TDM Reservation Protocol](https://w3c-cg.github.io/tdm-reservation-protocol/), [IETF AI Preferences draft](https://ietf-wg-aipref.github.io/drafts/draft-ietf-aipref-vocab.html), and [C2PA specifications](https://spec.c2pa.org/specifications/). Record the reference identity in export metadata.

Map only states the target format can express. Preserve conditional dimensions in JSON and label lossy projections. Do not flatten a restricted license into unconditional allow or invent standard tokens for REVIEW. C2PA export does not embed/sign a manifest. An artwork-specific ai.txt fragment requires installation on the publisher's origin; preferences do not guarantee compliance.

**Completion gate:** fixtures validate output syntax and conditional/unknown/revoked behavior; public summaries exclude contact details and all exports exclude secrets.

## Stage 5 — Persistent read-only provenance

Extend the existing official c2patool adapter/router instead of adding a competing verifier. Check configured binary identity. Bound execution time and stdout/stderr, and disable embedded remote-manifest/OCSP fetching. Keep manifest validity, signature validity, certificate information, and trust separate.

Normalize to VALID, VALID_BUT_UNTRUSTED, INVALID, ABSENT, UNSUPPORTED, PROVIDER_UNAVAILABLE, or PARSE_ERROR while keeping legacy packet states. Persist safe summaries for claim generator, creation/edit actions, AI/model declarations, timestamps, ingredient/parent relationships, thumbnail presence, repository references, C2PA version, and validation reasons. Hash inappropriate raw identifiers; omit raw provider dumps.

Inspect EXIF/IPTC/XMP with a bounded allowlist. Omit GPS, artist contact, comments, and arbitrary metadata. Reject entity-bearing XML and malformed metadata. Metadata absence must not be represented as proven stripping.

Persist registration and candidate inspection before zero-retention cleanup. Add authenticated work/scan inspect/read APIs. Missing media returns a documented 404, but existing safe records remain readable. Failed inspection can be retried into a new immutable record.

**Completion gate:** contract tests cover every state, invalid signatures, multiple ingredients, AI assertions, corrupt files, and unavailable providers. Separately smoke-test the installed official tool; do not claim trusted-signature validation without an appropriate real fixture.

## Stage 6 — Evidence Matrix and abstention

Project the authoritative existing packet into COPY, ORIGIN, PROVENANCE, CREATOR_PROFILE, RIGHTS, POLICY, SOURCE_COVERAGE, and INTEGRITY. Preserve each score and semantics rather than averaging unrelated probabilities.

Persist identity, provider/version, signal type/status, score/semantics, confidence, evidence quality, coverage, reasons, artifact references, input hash, timing bounds, error/fallback, and model/rule identity. Label whether timings are actual provider instrumentation or scan-stage projection bounds.

Implement deterministic SUPPORTED, PARTIALLY_SUPPORTED, INCONCLUSIVE, CONTRADICTORY, INSUFFICIENT_COVERAGE, and PROVIDER_FAILURE results. Explain missing lanes and source scope. Abstain on unresolved evidence, contradictions, inadequate source coverage, and terminal failure. Keep legal_conclusion null and recommend HUMAN_REVIEW where appropriate.

Retrieval neighbors and style resemblance stay advisory. Region references require validated geometric correspondence; failed geometry cannot create invented regions. An exact byte match can remain supported while an optional origin detector is unavailable.

Persist at finalization, including terminal failures. Queued/historical reads must not fabricate finalized rows. Corrections append numbered matrices and audit events without replacing old rows. Bind each matrix to the original packet commitment.

**Completion gate:** exact/partial copy, semantic/style-only, AI-only, missing and contradictory providers, insufficient scope, abstention, failures, and immutable corrections are tested.

## Stage 7 — Human Contribution Ledger

Add per-work append/read/verify APIs with typed actors/actions and same-tenant input/output asset references. Store actor, description, assets, software/model, optional prompt reference, human decision, event time, artifact/C2PA references, before/after hashes, creator, and append time.

Chain canonical event digests using sequence and previous-event digest. Validate ordering and continuity. Serialize appends; reject invalid references/hashes/action types and unbounded text. A manual correction is another event, not a mutation.

Derive only factual contribution-history descriptions, including UNKNOWN when history is missing or incomplete. Do not infer copyrightability.

**Completion gate:** original artwork, AI-assisted edits, selection, manual corrections, version ordering, hash-chain tampering, concurrent appends, and immutable writes are covered.

## Stage 8 — Policy-aware matching

Extend policy_store.py and the existing evaluator. Preserve exact/transformed/partial reuse, semantic similarity, style resemblance, claim, license, and organization policy as distinct facts. Match status remains detector-derived.

Add an optional typed scan use_context for territory, channel, audience, transformation, platform, model, and requested passport permission. Bind it in immutable ScanInputBinding and idempotency hashing; legacy clients omitting it retain their existing contract. Submission country is a declaration, not proof of residence or intended-use territory.

Check license status/dates/intended use and all restricted dimensions. Missing required dimensions cause REVIEW. Apply passport conditions separately, preserve deterministic organization rules, and record input snapshots and the selected policy version.

**Completion gate:** licensed exact copy passes by policy; unlicensed commercial copy reviews/blocks under organization rules; scope mismatch cannot pass; style-only evidence never becomes a copy accusation; legacy scans remain compatible.

## Stage 9 — Human-supervised investigation

Reuse server-side AI & Inference configuration and the configured model. Supply only minimized packet evidence and verified database facts. Treat metadata/descriptions as untrusted data, never instructions.

Require structured evidence references, missing facts, contradictions, next steps, summaries, and notice plans. Validate schema, facts, URLs, dates, and identifiers. Render notices deterministically from supplied factual paragraphs; limit the model to an allowed structured plan. The assistant cannot send, submit, approve, override policy, or invent authority/geography/license facts.

Persist provider/model/template, authoritative evidence-packet hash, separate generation-context hash, output hash, generation time, and a single accepted/edited/rejected reviewer transition. Preserve original output and store edits separately. Link legacy Admin drafts to investigation records without changing the UI.

Use timeouts, bounded responses, limited retries, and a circuit breaker. Record unavailable/failed outcomes and clearly label manual/deterministic fallbacks.

**Completion gate:** injection, fabricated facts/URLs, malformed output, timeout/retry/circuit behavior, packet mismatch, review races, and Admin notice regressions pass. Free-text summaries still require human checking.

## Stage 10 — Public verification and retention

Issue random public tokens, store only hashes, and serve stable versioned JSON at `/verify/{token}`. Scope tokens to work/scan; support expiry and revocation. Resolve tokens with narrowly privileged lookup, then bind subsequent reads to the tenant.

Expose only asset identifier, registration/provenance state, safe rights summary, timestamp, packet digest, public evidence version, and revocation information. Exclude raw media, private URLs/contact, embeddings, model payloads, prompts, and secrets. Mask token paths in logs. Use a public IP rate bucket that arbitrary API-key headers cannot bypass.

Enforce candidate TTL for successful/failed scans at finalization, startup, background maintenance, and media access. Delete candidate and derived artifacts together. Record receipts, retry failures using retained locators, and preserve finalized evidence. Work deletion removes media/active retrieval and revokes tokens while retaining explicitly documented immutable-history tombstones.

**Completion gate:** guessed/expired/revoked/foreign-tenant tokens, safe projections, logs/rate limits, zero/positive retention, missing objects, retry, media authorization, and deletion are tested.

## Stage 11 — Security and operational setup

Use local SQLite/queue/storage fallbacks. Keep API keys server-side. Recursively redact secrets in structured/exception logs. Protect external fetches against private addresses, DNS rebinding, and redirects; use connector allowlists. Enforce actual allowed image formats, byte/pixel/decompression limits, and corrupt/unsafe-file rejection.

Provide root scripts/phase1_preflight.py and setup docs. Default checks avoid paid calls; live checks are explicit opt-in. Distinguish CONFIGURED_NOT_LIVE_CHECKED, live-verified, unavailable, and deferred states without secret values. Wire API and worker settings consistently in Compose.

Optional missing credentials disable only their capability. Required missing credentials get exact provider/account/local-setting/validation instructions; never request a pasted secret. Phase 1 requires no blockchain wallet, email service, partner account, global search account, or training cluster.

**Completion gate:** preflight, configuration examples, Compose validation, redaction, SSRF, file handling, and dependency status are verified.

## Stage 12 — Integration tests and lawful benchmark

Run the existing API suite plus Phase 1 tests. Verify registration → scan → persisted provenance/matrix → policy → investigation → human review → safe public verification, plus Admin/monitor/notice/proof regressions. Run SQLite migration/adoption and actual PostgreSQL RLS/runtime/immutability checks when available.

Generate deterministic lawful originals and independently created hard negatives. Evaluate duplicate, JPEG, resize, crop, mirror, rotation, overlay/text, color shift/recolor, partial reuse, screenshot, similar subject, same subject/different creator, same palette/different composition, and style-like non-copy cases. Real AI image-to-image requires an authorized fixture and generation metadata; label unavailable otherwise.

Measure precision/recall/FPR/FNR, review-threshold burden per 1,000, retrieval/localization/geometry success, abstention, provider availability, p50/p95 latency, evidence completeness, and policy outcomes. Review time/override rate require actual reviewed cases; use null when unmeasured. Seal corpus/report manifests. A small smoke benchmark is a regression check, not a production accuracy claim.

Run backend lint/diff checks and compare frontend hashes. Refresh model-bundle application revision only after sources stabilize; report dependency/artifact drift honestly.

## Dependency order and release gate

Database foundation precedes new persistence. Rights/export, provenance/matrix, and assistant/provider work can run in parallel after schema contracts agree. Ledger/public routes reuse tenancy/immutability helpers. Policy integration follows typed rights/context contracts. Finish with retention/security, full regression, benchmark, and frontend protection.

Deliver audit, access checklist, this plan, provider setup, rights passport, evidence matrix, C2PA/provenance, contribution ledger, policy engine, security, testing, and PHASE1_IMPLEMENTATION_REPORT.md.

The report must map each requirement to implementation and validation, then list unavailable, deferred, and untested behavior separately. Completion requires untouched frontend, passing existing user/Admin/proof flows, versioned policies, immutable evidence/ledger, working deterministic policy examples, hash-bound supervised assistant results, safe public JSON, working SQLite, accurately reported PostgreSQL checks, and complete access/limitations documentation.
