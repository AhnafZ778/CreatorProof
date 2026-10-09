# Phase 1 internal smoke benchmark

`final-offline-smoke.v1.json` records a fresh final 67-case run using the same
four-source, seed-731 corpus recipe. Its observed source revision matches the
application revision in the bundle, and its manifest/prediction/metric/report
digests are recorded. The run returned 45 true positives, three false negatives,
zero false positives and 16 true negatives; three separately labeled policy
scenarios passed. Its p50/p95 latency was 1100.018/1447.157 ms. It remains
`SMOKE_TEST_ONLY` and evaluation/promotion-ineligible. The declared model runtime
environment still has package-version drift; the observed `demo_ready` is false.
Do not interpret the bundle's declared `RUNTIME_READY` state as verified model
qualification.

`offline-smoke.v1.json` is an actual 67-case in-process API run over four locally
generated procedural source lineages, 12 reuse transformations, four independent
negative cohorts, and three permission/coverage scenarios. `benchmark.json` and
`corpus.json` preserve its byte hashes and declared input labels. Image bytes are
generated locally and are not checked into the repository.

To reproduce the corpus, run the root `scripts/phase1_benchmark.py` generator with
`--sources 4 --seed 731` into a new directory, then run that manifest. Do not run
the archived manifest directly: its image paths refer to the generated corpus.

This run used the offline baseline with SSCD, origin, provenance and creator
profile providers unavailable. AI image-to-image fixtures were unavailable.
Review time and human override were not measured. It was recorded during Phase 1
development and is an integration smoke artifact, not a source-locked model
acceptance report or real-world accuracy claim. No thresholds were tuned against
these fixtures. See `docs/PHASE1_TESTING.md` for metrics and limitations.

`postgresql17-verification.v1.json` records a separate actual disposable
PostgreSQL 17 run: empty migration, historical migration/backfill, `create_all`
adoption, runtime-role RLS, tenant foreign keys, database immutability and
one-time human review. It records the observed server version and successful
container cleanup. Reproduce it using `scripts.phase1_postgres_verify` from
`apps/api`; it generates its own credentials and never uses the configured
application database.

`c2pa_local_smoke.json` records actual official-tool inspection of locally
generated unsigned PNG bytes (under PNG and BIN names) and corrupt bytes. Signed
trusted/tampered/AI-asserting fixtures were not live-qualified.
