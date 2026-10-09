# Phase 1 testing and internal benchmark

Phase 1 verification includes API integration tests, schema/migration checks,
provider-contract tests, security cases, existing regressions, and a procedural
image benchmark. A successful internal run does not establish real-world
accuracy, legal correctness, or permission to automatically send a notice.

## Run the backend suite

From the repository root:

```bash
cd apps/api
.venv/bin/python -m pytest -q
.venv/bin/ruff check app scripts tests migrations
```

Focused Phase 1 coverage is in `tests/test_phase1_*.py`. Run it with the existing
migration, scan, evidence, proof, authentication, and admin regression tests:

```bash
.venv/bin/python -m pytest -q tests/test_phase1_*.py \
  tests/test_production_database_safety.py tests/test_scan_flow.py \
  tests/test_admin_monitor.py tests/test_provenance_contract.py \
  tests/test_signing_and_transparency.py tests/test_rls_sessions.py
```

The tests exercise:

| Area | Evidence checked |
|---|---|
| Rights and policy | Explicit preference values, expiry/revocation, use and geographic restrictions, creator assertions, deterministic exports and policy decisions |
| Provenance | Trusted/untrusted/invalid/absent/unsupported/unavailable states, ingredients, AI action declarations, metadata stripping and malformed images |
| Evidence | All eight lanes, provider contradictions, semantic/style-only evidence, abstention, geometry artifacts, coverage and immutable correction versions |
| Contributions | Human and AI-assisted event fields, hash chains, unique sequence, append-only records and asset references |
| Investigation | Structured provider output, packet/input/output hashes, prompt injection, invented-fact rejection, unavailable fallback and a single attributable human disposition |
| Privacy/security | Secret redaction, scope/tenant boundaries, public tokens, SSRF, media limits, zero retention, evidence-access events and safe deletion |
| Persistence | Empty and existing SQLite migrations, `create_all` adoption, same-tenant foreign keys, SQL immutability and UNKNOWN rights backfill |
| Compatibility | Existing scan/admin packets, signed proof and audit behavior; no new frontend source changes |

Provider mocks prove normalized behavior and failure handling. They do not prove
that a provider is currently reachable, that a signing certificate is trusted,
or that a detector is calibrated. The preflight's `--live` mode checks only
database `SELECT 1` and Redis `PING`; it does not call external image/AI vendors
or run media inspection. Validate a remote provider through a separately
authorized creator-owned scan/investigation, and inspect its recorded provider,
coverage, and failure state. Record live provider tests separately from the unit
suite and never include credentials in an artifact.

## Migrations and PostgreSQL

The migration tests cover both an empty SQLite database and databases created
through `Base.metadata.create_all`. They also upgrade historical Phase 1
contributions, preserving their creation timestamp and binding related rows to
the same tenant. `alembic check` must report no pending operations.

SQLite installs database triggers through migration 0012 and after quick-start
`create_all`. Raw SQL, ORM bulk writes and `INSERT OR REPLACE` cannot rewrite,
delete or replace immutable records. Tests exercise all 20 immutable tables in
both schema paths. The established exceptions are a signed statement's current
status projection, a checkpoint's first external commitment and an
investigation output's first complete human disposition. Generated content
remains unchanged. The SQLite file owner can alter its schema; portable hashes
and signatures separately detect compromised storage.

Migration 0013 adds an all-UNKNOWN rights version only for active works that
have no policy. It preserves existing policies and deleted works and records no
invented historical consent, ownership or signed registration event. Its digest
is checked against the normal rights-policy canonical projection.

Run deployment migrations through the existing migration script with the
migration-owner URL configured locally. The application must then start with a
separate PostgreSQL runtime role that owns no migration-managed tables, has no
`SUPERUSER`/`BYPASSRLS`, and observes forced RLS. On a configured test PostgreSQL
database, verify same-tenant reads, cross-tenant denials, system-worker override,
append-only triggers, first human-disposition transitions, and startup safety.
SQLite success alone does not prove PostgreSQL policy enforcement.

An opt-in verifier creates a uniquely named PostgreSQL 17 Docker container bound
to localhost, generates disposable owner/runtime credentials, and removes the
container in `finally`. It never reads or prints a configured database URL.

```bash
cd apps/api
.venv/bin/python -m scripts.phase1_postgres_verify \
  --report benchmarks/phase1/postgresql17-verification.v1.json
CREATORPROOF_RUN_DISPOSABLE_POSTGRES=1 .venv/bin/python -m pytest -q \
  tests/test_phase1_postgres_live.py
```

The verifier checks empty migrations, `create_all` adoption, a historical
32-character Alembic version table, legacy immutable contribution and evidence
matrix-linkage backfills under forced RLS, UNKNOWN rights backfill,
schema parity, forced RLS under a nonowner runtime role, same-tenant foreign keys,
worker override across commits, direct-SQL evidence mutation rejection,
investigation content immutability, one human disposition, and actual API startup.
It uses the existing `postgres:17-alpine` image or pulls it when absent. The
archived JSON identifies the exact server version observed and whether cleanup
succeeded. The default pytest suite skips this Docker test explicitly.

## Generate and run the lawful internal image benchmark

The generator creates test artwork locally with deterministic procedural shapes
and strokes. It downloads no images. These fixtures are authorized internal
material generated by repository code; they do not claim to be copyrighted
human artwork or outputs from an AI generation model.

From the repository root, choose a new directory for each generated dataset:

```bash
apps/api/.venv/bin/python scripts/phase1_benchmark.py generate \
  --output /tmp/creatorproof-phase1-benchmark --sources 4 --seed 731
apps/api/.venv/bin/python scripts/phase1_benchmark.py run \
  /tmp/creatorproof-phase1-benchmark/benchmark.json
```

Generation writes byte-hashed `corpus.json`, `benchmark.json`, and local images.
The corpus uses the existing manifest validator and is marked `DEMO` and
`DEMO_EXPOSED`. Exact-duplicate cases reference the same authorized bytes rather
than hiding duplicate assets inside the corpus.

The runner creates an isolated SQLite database and private local object store,
registers references through `/v1/works`, submits cases through `/v1/scans`, and
reads `/v1/scans/{id}/evidence-matrix`. It leaves the project's existing database
and models unchanged. The report is written to `report.json` beside the dataset.
Each report uses the existing benchmark identity, prediction digest, metric-input
digest, report seal, and validation infrastructure.

The default runner invokes no remote providers. It runs the existing hash,
geometry, alignment and copy-fusion behavior. A missing SSCD provider is recorded
as unavailable. To measure the installed local SSCD runtime, supply its existing
hash-pinned artifact explicitly:

```bash
apps/api/.venv/bin/python scripts/phase1_benchmark.py run \
  /tmp/creatorproof-phase1-benchmark/benchmark.json \
  --local-sscd-model apps/api/models/sscd_disc_mixup.torchscript.pt
```

An artifact's presence does not prove that loading succeeded; check
`provider_availability.copy_retrieval_sscd`. Use `--max-cases 4` for a short
integration smoke run. It is a subset run and cannot represent the full cohort.

### Transformation and negative cohorts

| Cohort | Construction |
|---|---|
| Exact duplicate | Identical source bytes |
| JPEG recompression | Quality-55 recompression |
| Resize | 50% resize |
| Crop | Known source crop |
| Mirror | Horizontal reflection |
| Rotation | 8-degree rotation |
| Overlay | Opaque controlled banner |
| Text overlay | Banner and internal test caption |
| Color shift | Reduced saturation |
| Recoloring | Deterministic grayscale-to-blue mapping |
| Partial reuse | Known source patch inside independent procedural artwork |
| Screenshot | Artwork embedded in a locally created viewer frame |
| AI image-to-image | Unavailable unless authorized generated fixtures are supplied |
| Unrelated similar subject | Independently constructed shapes |
| Same subject, different creator | Artificial proxy using an independent procedural lineage; no real creator attribution claim |
| Same palette, different composition | Independently positioned/stroked artwork |
| Style-like non-copying | Independent artwork with shared shape vocabulary |

The generator also adds explicit licensed-use, unlicensed-use and empty-catalog
cases so policy accuracy and correct abstention have known labels independent
from detector accuracy.

### Supply real authorized AI image-to-image fixtures

No procedural transform is mislabeled as an AI generation. A model declaration
alone does not establish image origin; fixture provenance is a supplied benchmark
record. Use a local manifest whose paths stay inside its directory:

```json
{
  "cases": [
    {
      "reference": "reference.png",
      "query": "image-to-image.png",
      "copy_label": true,
      "model": "actual-generator-and-version",
      "generation_record": "local-record-or-artifact-hash",
      "rights": {
        "state": "AUTHORIZED",
        "reference": "local-permission-record"
      }
    }
  ]
}
```

Add it during generation with `--authorized-ai-fixtures /path/to/fixtures.json`.
The importer requires authorization, a generation record, a model identifier,
and a manually supplied boolean correspondence label. It copies only validated
local images and performs no downloads. The copy label describes benchmark
correspondence, not infringement or legal ownership.

## Interpret the report

The report provides precision, recall, retrieval recall, FPR/FNR, precision at the
review threshold, observed false-positive burden per 1,000 negative scans,
geometry validation, localization, abstention, provider availability, p50/p95
end-to-end latency, evidence completeness and policy accuracy.

The denominators and limits matter:

- Copy rates exclude the separately labeled policy/coverage scenarios.
- Retrieval recall means the expected registered reference appeared in the
  returned candidate list. It does not claim an ANN benchmark.
- Review-threshold positives are `MATCH_FOUND` or `INCONCLUSIVE` scan outcomes.
- Localization is measured only for partial-reuse/screenshot cases with known
  query support. It requires valid geometry and region-envelope centers inside
  the known reused rectangle. It is not segmentation IoU.
- Correct abstention is scored only where an explicit expected-abstention label
  exists; the report includes that labeled-case count.
- Evidence completeness means required packet fields and persisted signals for
  all eight lanes exist, including explicit unavailable/not-run signals. It does
  not mean all providers succeeded or all claims are corroborated.
- Policy accuracy is measured only against the three explicit policy/coverage
  expectations. Detector errors and policy errors remain separate.
- Human review time and override rate remain `null` until measured in an actual
  review exercise. They are never inferred from AI or API latency.
- AI origin, provenance and creator-profile provider availability is false in
  this offline benchmark. Contract tests, local media inspection smoke tests,
  and separately authorized remote provider checks are separate evidence;
  preflight `--live` does not qualify these providers.
- A low observed FPR in this small sample does not establish a population burden
  of one false positive per 1,000 scans. The report keeps acceptance false.

Reports remain `SMOKE_TEST_ONLY`, evaluation-ineligible and promotion-ineligible.
Do not tune thresholds to make these exposed fixtures pass and then report them
as held-out evaluation. Production evaluation needs a larger authorized corpus
with independent source/creator/transform lineages and reviewed acceptance gates.

## Protect the frontend baseline

Phase 1 adds backend behavior only. Compare the current frontend files to the
recorded pre-implementation hashes/list in the repository audit and run the
frontend protection check used by the implementation report. Existing dirty
frontend files are the baseline; they must not be reset, reformatted or included
as new Phase 1 changes. Preserve existing API response fields while adding new
backend fields and routes.
