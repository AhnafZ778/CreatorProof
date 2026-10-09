# CreatorProof Phase 1 implementation report

> This records the completed backend-only phase. The later, explicitly requested
> [frontend integration](docs/FRONTEND_INTEGRATION_REPORT.md) exposes these
> capabilities in Artist, User and Admin portals and adds an interactive pipeline.
> Its frontend changes supersede the original UI freeze for that later phase.
> The subsequent [Artist/Admin simplification and User handoff update](docs/ADMIN_ARTIST_SIMPLIFICATION_REPORT.md) groups those tools and persists all completed flags for Admin review.
> The [stored comparison update](docs/STORED_CASES_IMPLEMENTATION_REPORT.md) adds a ready-to-open Admin collection with saved image pairs, recorded matches and prepared notices.
> The [evidence verdict update](docs/EVIDENCE_VERDICTS_REPORT.md) replaces mixed lane badges with specific assessments and distinguishes supported reuse, recorded permission conflicts and unresolved authorization.
> The [measured ratings update](docs/EVIDENCE_RATINGS_REPORT.md) adds numeric model indices, specific reuse verdicts and full saved assessments for the three stored image comparisons.
> The [Artist registration design update](docs/ARTIST_REGISTRATION_DESIGN_REPORT.md) adds a spacious image-preview form, clearer fields and a responsive layout matching the Artist portal.

Recorded on 2026-10-09. Phase 1 extends the backend rights, evidence, persistence,
security and operational infrastructure. The detailed sequence and acceptance
gates are in [the implementation plan](PHASE1_IMPLEMENTATION_PLAN.md).

This implementation keeps visual reuse, origin, creator resemblance,
provenance and permission separate. Automated results do not establish
ownership, infringement, copyrightability, residence, or authority to send a
notice. The assistant cannot send notices or override deterministic policy.

## Implemented capabilities and evidence

| Requirement | Implementation | Validation and practical boundary |
|---|---|---|
| Versioned AI Rights Passport | Typed eleven-permission policy, six values, effective dates, attribution/license conditions, geography/platform/model restrictions, consent/revocation, creator assertion and corroborating references. Each registration receives a neutral all-UNKNOWN baseline; explicit updates append versions. | Passport/policy/schema integration tests cover values, history, scope, expiry, revocation, tenant isolation and baseline neutrality. Declarations remain assertions, separate from signed licenses and organization rules. |
| Machine-readable preferences | JSON, ai.txt fragment, TDM projection, AI Preferences projection and human-readable statement with version/digest/identifier. Conditional states remain visible in JSON; coarse adapters return mapping reasons. | Exports are deterministic and conservative. Broad TDM permission requires an explicit compatible reservation dimension. C2PA usage authoring is reported unsupported for the pinned specification; no deprecated assertion or signed manifest is fabricated. |
| Read-only C2PA/provenance | Existing official c2patool adapter extended with bounded subprocess execution and parsing, seven normalized states, safe metadata/actions/ingredients, immutable work/scan inspections and read/inspect routes. | Contract tests cover valid/untrusted/invalid/absent/unsupported/unavailable/error cases, multiple ingredients, AI declarations, malformed metadata and subprocess resource limits. Actual local tool smoke covers unsigned and corrupt bytes; real trusted signed fixtures remain unqualified. |
| Persisted Evidence Matrix | Eight lanes with individual semantics, provider/model identity, status/quality/coverage, reasons, artifact references, input hashes and timing bounds. Six deterministic final states and explicit abstention. Finalized/failure packets persist matrices; corrections append versions. | API and service tests cover exact/partial reuse, semantic/style-only evidence, AI/copy separation, contradictions, missing providers, no invented regions, failure/cancellation and immutable history. Completeness represents explicit lane states, including unavailable lanes. |
| Human Contribution Ledger | Typed append/read/verify API with actors/actions, assets, software/model, prompt reference, human decision, timestamps, before/after hashes, artifacts and C2PA references. Ordered canonical hash chain and factual history categories. | Tests cover human work, AI-assisted editing, selection/correction, sequence/chain verification, cross-tenant references and forbidden mutation. Unknown history remains unknown; no copyrightability decision is produced. |
| Policy-aware matching | Existing policy evaluator extended with passport snapshots, licenses and optional typed intended-use context. Territory/channel/audience/transformation/platform/model/requested permission are bound in the immutable scan input. | Integration tests prove a licensed exact copy can pass while missing or mismatched scope reviews. Style/semantic evidence remains advisory. Country submission does not prove residence or silently set intended-use territory. Legacy clients without context retain their contract. |
| Supervised investigation | Structured backend assistant over minimized packet/database facts, provider/model/template identities, authoritative packet hash, context hash, immutable output hash, generation time and one attributable accepted/edited/rejected disposition. Legacy Admin drafts link to investigation outputs. | Tests cover injection, invented URLs/dates/IDs, malformed output, hash mismatch, retry/timeouts/circuit breaker, unavailable fallback and review races. Notices use factual paragraph plans rendered from supplied facts. Free-text summaries still require human checking. |
| Public verification | Random 48-byte bearer tokens stored as hashes; scoped issuance, expiry, revocation and stable safe JSON. Scan policy summaries bind to the policy used at scan time; work summaries reflect current policy. | Tests cover scope/tenants/guessing/expiry/revocation, safe fields, token-redacted logs/metrics and IP-based admission that ignores rotating untrusted API-key headers. No contact details, embeddings, raw candidate media, private URLs or provider payloads are exposed. |
| Retention and deletion | Zero/positive candidate TTL enforced at completion, media access, startup and maintenance. Candidate/derived objects are deleted together; failed deletion retains a retry locator and receipt. Work deletion removes media/active access and revokes tokens while preserving immutable-history tombstones. | Integration tests cover running/completed/failed scans, expiry, missing objects, deletion failure/retry, authenticated media access and retained evidence. A deleted candidate cannot later be compared visually unless retention was explicitly configured. |
| Database and tenancy | Ten new Phase 1 entities, composite same-tenant foreign keys, immutable versions/signals/contributions/generated content, forced PostgreSQL RLS, and SQLite SQL-level immutability. | Empty/adopted/historical SQLite migration tests and a real PostgreSQL 17.10 verifier pass. Twenty immutable tables receive SQLite guards. Documented operational projection exceptions do not allow generated evidence content to change. |
| Provider/security operations | Server-side configuration, recursive credential redaction, bounded provider requests, safe pinned-IP outbound fetches, redirect/private-address rejection, actual image-format and decompression limits, preflight and provider setup. | Security/format/SSRF/authentication/observability tests pass. Unsafe-file rejection is implemented; a general-purpose antivirus service is not claimed. Optional provider failures remain visible and do not invent evidence. |
| Frontend protection | Frozen pre-implementation membership and hashes cover tracked and untracked frontend source files. Additive APIs preserve existing response fields and legacy packet vocabulary. | All 105 frontend files match the frozen worktree baseline. Existing dirty frontend work predates Phase 1 and was preserved. No frontend build/design changes are part of this phase. |

## Main backend entry points

Routes follow the existing `/v1` convention; the public verifier uses `/verify`.
Protected endpoints use existing tenant authorization and audit infrastructure.

| API | Purpose |
|---|---|
| `POST/GET /v1/works/{id}/rights-policy` | Append/read current passport; `GET .../rights-policy/{version}` reads history |
| `GET /v1/works/{id}/ai-preferences` | Structured preferences, mapping identity and limitations |
| `GET /v1/works/{id}/ai.txt`, `/tdm-policy`, `/rights-statement` | Preference exports |
| `POST /v1/works/{id}/provenance/inspect`, `GET .../provenance` | Registered-source inspection and safe history |
| `POST /v1/scans/{id}/provenance/inspect`, `GET .../provenance` | Candidate reinspection while retained; persisted inspection read |
| `GET /v1/scans/{id}/evidence-matrix` | Latest persisted normalized matrix |
| `POST /v1/scans/{id}/evidence-matrix/corrections` | Append an authorized correction with reason and prior-version linkage |
| `POST/GET /v1/works/{id}/contributions`, `GET .../contributions/verify` | Contribution append/read/chain verification |
| `POST /v1/investigations/scans/{id}` | Generate a supervised, packet-bound investigation |
| `GET /v1/investigations/{id}`, `POST .../{id}/decision` | Inspect and record one human disposition |
| `POST /v1/works/{id}/verification-token`, `POST /v1/scans/{id}/verification-token` | Issue scoped public tokens |
| `DELETE /v1/verification-tokens/{id}` | Revoke a token |
| `GET /verify/{token}` | Safe versioned public JSON |

The exact payloads, authorization scopes, failure statuses and limitations are
documented in [rights passport](docs/AI_RIGHTS_PASSPORT.md),
[evidence matrix](docs/EVIDENCE_MATRIX.md), [provenance](docs/C2PA_PROVENANCE.md),
[contribution ledger](docs/HUMAN_CONTRIBUTION_LEDGER.md), and
[policy engine](docs/POLICY_ENGINE.md).

Implementation extends `models.py`, existing work/scan/rights/review routes,
policy/evidence/scan-runner services, queue workers, storage and observability.
New feature modules are `routes/passports.py`, `routes/phase1.py`,
`routes/investigations.py`, `services/rights_passport.py`,
`services/rights_baseline.py`, `services/provenance_records.py`,
`services/evidence_matrix.py`, `services/retention.py`, `services/safe_http.py`,
and `sqlite_integrity.py`. The existing `services/aiand.py` and Admin draft
flow were hardened rather than adding a second notice-delivery system.

## Migration and integrity results

Migrations 0009–0013 add the Phase 1 foundation, full typed relationships,
PostgreSQL index parity, SQLite immutability and missing all-UNKNOWN policies.
Migration adoption also handles legacy 32-character Alembic revision storage
without renaming historical revision identities. Backfills preserve existing
policies, deleted works, contribution timestamps and immutable content; system
override is explicit when PostgreSQL forced RLS requires it.

The workspace's existing local SQLite database was backed up using SQLite's
online backup API, checked, and upgraded through
`0013_unknown_rights_baseline`. The private backup is
`apps/api/data/backups/creatorproof-20261009T083431Z-xe_843mm.db`; it is an
ignored operational artifact and must not be published. `alembic check` reported
no new upgrade operations.

Actual PostgreSQL testing used a disposable `postgres:17-alpine` container,
observed server 17.10, and generated temporary owner/runtime credentials. All
15 checks passed: empty/historical/create_all upgrades, schema parity,
UNKNOWN-policy backfill, legacy evidence/contribution preservation, forced RLS,
unbound and cross-tenant access denial, worker override across commits,
cross-tenant foreign-key rejection, direct-SQL immutability, one human review,
and real application startup with a restricted runtime role. The container was
removed. See [the archived PostgreSQL report](apps/api/benchmarks/phase1/postgresql17-verification.v1.json).

SQLite SQL guards reject update/delete/replacement of immutable records; an
operator with ownership of the database file can still alter its schema.
Portable hashes and existing signatures provide a separate tamper-evidence
mechanism. A hash establishes byte commitment, not ownership.

## Final automated verification

The final complete backend suite passed: **796 passed, 3 skipped, zero failures**
in 260.53 seconds. Command from `apps/api`:

```bash
uv run pytest -o addopts='' -q -ra --tb=short
```

The three skips are explicit: optional blockchain `eth_account` is absent, the
Docker PostgreSQL test requires its opt-in flag (and passed separately), and one
legacy scan test did not open a review case because its result did not require
review. One TorchScript deprecation warning came from the successful real local
SSCD scan test. No test failure was hidden or marked expected.
See [the structured final verification artifact](apps/api/benchmarks/phase1/final-verification.v1.json).

The full run includes existing user scans, Admin/monitor/drafts, evidence,
proof/signing/transparency, tenant/RLS behavior, uploads and all Phase 1 tests.
Additional verification:

- `uv run ruff check app scripts migrations tests`: passed.
- `uv run alembic check`: passed after the local migration.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.
- `python3 scripts/phase1_frontend_guard.py`: 105 files, zero changes.
- The opt-in real PostgreSQL pytest entry point passed separately; default
  pytest skips Docker execution explicitly.
- Actual local official C2PA smoke: unsigned PNG bytes under PNG/BIN filenames
  normalized to ABSENT, and corrupt bytes to PARSE_ERROR, with signature/trust
  left unknown. See [the smoke artifact](apps/api/benchmarks/phase1/c2pa_local_smoke.json).

The frontend comparison includes path membership and SHA-256 for both tracked
and untracked sources. [The baseline](docs/phase1-frontend-baseline.json) and
[comparison report](docs/phase1-frontend-verification.json) show no Phase 1 diff.
The [frontend diff report](docs/PHASE1_FRONTEND_DIFF_REPORT.md) explains the Git
worktree boundary and comparison method.
`git diff HEAD -- apps/web` still shows prior user work; resetting that work would
be incorrect. The comparison baseline is the worktree at Phase 1 start.

## Fresh lawful offline benchmark

The final run uses four procedurally generated source lineages, 12 controlled
reuse transformations, four independent hard-negative cohorts and three explicit
policy/coverage scenarios: 67 total API cases. No copyrighted artwork was
downloaded. Corpus/input hashes, predictions, metric inputs and report seal are
archived in [final-offline-smoke.v1.json](apps/api/benchmarks/phase1/final-offline-smoke.v1.json).

| Metric | Observed result and denominator |
|---|---|
| Confusion counts | 45 TP, 3 FN, 0 FP, 16 TN; three policy scenarios evaluated separately |
| Copy precision / recall | 1.0 / 0.9375 |
| Retrieval recall | 0.958333; expected registered reference in returned candidates |
| False-positive / false-negative rate | 0 / 0.0625 |
| Precision at review threshold | 0.774194; threshold includes inconclusive results |
| Observed false positives per 1,000 negative scans | 0; only 16 negatives, population burden not established |
| Geometry validation rate | 0.9375 |
| Localization success | 8/8 eligible partial-reuse/screenshot cases; support-envelope localization, not pixel IoU |
| Abstention / review rate | 0.268657 / 0.283582 |
| Correct abstention | 1/1 explicitly labeled case; insufficient basis for population estimates |
| Median / p95 end-to-end latency | 1100.018 / 1447.157 ms on this local offline run |
| Complete persisted evidence packets | 67/67; explicit unavailable signals count as structural completeness |
| Policy-decision accuracy | 3/3 labeled scope/policy scenarios |
| Review time / human override | Unmeasured (`null`) |

Local hash/geometry/alignment ran; SSCD, origin, creator-profile and provenance
were explicitly disabled/unavailable in this offline benchmark. Real AI
image-to-image fixtures were unavailable. The runner can accept authorized local
AI fixtures with rights and actual model/generation metadata; it never relabels
a procedural transform as AI-generated. A separate automated test exercised the
installed local SSCD runtime; that is a load/integration check, not calibration.

The final benchmark source revision matches the application's recorded source
revision. The sealed report digest is
`e418bc20ad4bba09149873404a3e4a3ad51217bf18a57c23139b1994f3daafe7`.
The corpus is exposed procedural smoke data: evaluation/promotion eligibility
remain false, no thresholds were tuned for this run, and no real-world accuracy
or acceptable false-positive burden is claimed. Reproduction commands and cohort
limits are in [the testing guide](docs/PHASE1_TESTING.md).

## Actual local access and qualification state

Preflight was run with `--live`. This option checks database/Redis connectivity,
not billable remote provider contracts. It returned valid configuration with no
required-capability failures, SQLite LIVE_REACHABLE, local queue configured and
local storage accessible. Candidate retention is zero, so media is deleted
after scanning while evidence persists.

| Capability | Actual observation |
|---|---|
| Official C2PA tool | Binary/version identity verified; 0.27.7; actual unsigned/corrupt smoke succeeded |
| Sightengine | Configured; not live-checked in Phase 1 |
| AI & Inference | Configured with preserved `deepseek-ai/deepseek-v4-flash`; not live-checked in Phase 1 |
| Unsplash / Pixabay | Configured; not live-checked in Phase 1; optional connectors |
| Managed PostgreSQL / Redis / S3 | Not required by the current local deployment; no managed-service qualification claim |
| Model bundle source/artifacts | Application revision matches; installed SSCD artifact hash verified |
| Model runtime environment | Declared environment does not match installed optional model packages; qualification remains false |
| Model terms qualification | Required SSCD component remains `REVIEW_REQUIRED`; bundle `terms_failures` lists `copy-retrieval-sscd` |

The application revision is
`creatorproof-source-tree-sha256:c6817076d8558033e59d8821a0c7a22593a60406e4208ac2566d9c1e9196d9d9`.
Only the application's source-revision binding was refreshed after code froze.
Model environment pins were preserved:

| Package | Declared bundle | Installed |
|---|---|---|
| torch | 2.13.0 | 2.14.1+cpu |
| torchvision | 0.28.0 | 0.29.1+cpu |
| huggingface-hub | 1.27.0 | 1.33.0 |

Preflight configuration validity and API readiness do not certify model accuracy
or erase this drift. Model runtime qualification must be rerun against a chosen
compatible environment and an appropriate evaluation corpus before claiming a
qualified production detector. The existing manifest's declared RUNTIME_READY
label is reported separately from verification of that declaration.
The bundle's existing model-use terms checks also remain unresolved; their
states were preserved rather than relabeled as approved by this implementation.
See [the exact local preflight artifact](apps/api/benchmarks/phase1/local-preflight.v1.json).

## Unavailable, deferred and untested behavior

**Unavailable in the final offline evaluation:** remote origin detection,
learned SSCD retrieval, creator-profile evidence, provenance inspection and real
AI image-to-image fixtures. These lanes were deliberately reported unavailable
in that run; production configuration is evaluated independently. No required
external credential is missing for local rights/evidence/backend operation.

**Deferred by Phase 1 scope:** frontend consumption/design changes, signed C2PA
authoring/usage assertions, TrustMark embedding, trusted signing certificates,
automatic email/platform takedown submission, public-chain deployment or gas,
global reverse-image search, additional marketplace partnerships, custom model
training and population-scale accuracy qualification.

**Untested live:** current remote credentials/quotas for Sightengine, AI &
Inference, Unsplash and Pixabay; managed PostgreSQL/Redis/S3 deployments; real
trusted signed/tampered/AI-asserting C2PA fixtures; current online certificate
revocation; human review duration/override rate; actual AI image-to-image origin
accuracy. C2PA network manifest/OCSP fetching is disabled for the read-only local
inspection path, so current online revocation status is not claimed.

Assistant fact constraints and deterministic notice rendering are tested, but
general model summaries can still require corrections during human review.
Submission country and public source metadata never establish a person's actual
residence. Local deletion of media does not erase immutable historical evidence;
the documented tombstone/receipt states make this distinction explicit.

## Deliverables and operational handoff

All requested artifacts are present:

- [Repository audit](PHASE1_REPOSITORY_AUDIT.md),
  [access checklist](PHASE1_ACCESS_CHECKLIST.md), and
  [detailed implementation plan](PHASE1_IMPLEMENTATION_PLAN.md).
- [Provider setup](docs/PHASE1_PROVIDER_SETUP.md),
  [rights passport](docs/AI_RIGHTS_PASSPORT.md),
  [evidence matrix](docs/EVIDENCE_MATRIX.md),
  [C2PA/provenance](docs/C2PA_PROVENANCE.md),
  [contribution ledger](docs/HUMAN_CONTRIBUTION_LEDGER.md),
  [policy engine](docs/POLICY_ENGINE.md),
  [security](docs/PHASE1_SECURITY.md), and
  [testing/benchmark](docs/PHASE1_TESTING.md).
- [.env.example](.env.example),
  [root preflight](scripts/phase1_preflight.py),
  [lawful benchmark helper](scripts/phase1_benchmark.py), and this report.

Secrets stay in local environment files or a secret manager. Exact existing
environment names, setup URLs, account/permission steps, fallback, rotation and
revocation instructions are in the access/provider guides. Do not paste keys
into chat or put them into frontend code, public verification or fixtures.

From the repository root, configuration can be checked without exposing values:

```bash
python3 scripts/phase1_preflight.py --live
python3 scripts/phase1_frontend_guard.py
```

Run protected backend APIs with the existing authentication setup. To exercise
remote detectors/assistant, submit an authorized image and inspect actual
provider status/coverage and supervised investigation output. That additional
operational qualification is separate from the passing local code/migration
checks and does not authorize automatic notices.
