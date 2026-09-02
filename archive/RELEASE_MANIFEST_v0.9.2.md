# CreatorProof v0.9.2 — release manifest

Build: `0.9.2 / SEMANTIC-SAFETY-SCOPE-2026.08.10`

## Release purpose

v0.9.2 is a semantic-safety patch. It does not claim a new model-accuracy result. It removes paths
that could overstate search coverage, silently reuse an idempotency key for changed content, let an
uncorroborated rights record authorize use, or allow an informational AI-origin lane to behave like a
required policy gate.

## Shipped contract changes

- Typed coverage states: `COMPLETE`, `EMPTY_SCOPE`, `PARTIAL`, `DEGRADED`, `TRUNCATED`, `FAILED`.
- Typed capability execution states and coverage reason codes.
- Eligible catalog manifest, catalog version, snapshot digest, provider/preprocessing identity,
  query counts, candidate limit, verification counts, and omitted-reference reasons.
- Fail-closed decision gate: no source-scoped no-match unless coverage is complete.
- Canonical scan request digest over candidate SHA-256, normalized catalog, and intended use.
- Typed `409 IDEMPOTENCY_PAYLOAD_MISMATCH` for key reuse with a changed request.
- Explicit AI-origin modes: `DISABLED`, `INFORMATIONAL`, `REQUIRED`.
- Claim-state authorization: only `CORROBORATED` can authorize an otherwise allowed use.
- Recorded policy version, inputs, and reason codes in every completed Evidence Packet.
- Creator-facing terminology changed to **creator-profile resemblance** and **catalog-relative
  empirical support**.
- Uncalibrated passive AI detectors cannot emit the high-authority likely-AI classification.
- Source coverage and AI-origin policy effect are visible in the Evidence Microscope.

## Compatibility

- The HTTP paths remain `/v1`.
- `complete_for_declared_catalog` remains as a compatibility field; `coverage_status` is authoritative.
- Existing scan database columns are sufficient because `request_digest` is deterministically derived
  from stored immutable request fields. No destructive migration is required for this patch.
- The Evidence Packet keeps its v1 envelope and adds typed fields; evolving lane-specific fields remain
  forward-compatible.

## Default safety posture

- `CREATORPROOF_SYNTHETIC_POLICY_MODE=INFORMATIONAL`.
- `CREATORPROOF_COPY_RETRIEVAL_REQUIREMENT=LEARNED_REQUIRED`.
- With learned retrieval required, a missing/failed SSCD query or reference descriptor produces
  degraded scope and prevents a no-match pass.
- Deterministic tests explicitly use `BASELINE_ALLOWED` to exercise the approved pHash fallback path.
- New work registration defaults to `ASSERTED`, which cannot authorize use.

## Validation record

Executed on 2026-08-10:

- `apps/api/.venv/bin/pytest` → **85 passed**.
- `apps/api/.venv/bin/ruff check app tests scripts` → **passed**.
- `apps/api/.venv/bin/ruff format --check app tests scripts` → **passed**.
- `apps/web/npm run typecheck` → **passed**.
- `apps/web/npm run build` → **passed** with Next.js 16.3.0.

The backend suite still reports a Starlette/httpx deprecation warning and two upstream TorchScript
deprecation warnings. They do not fail this patch but remain dependency-maintenance work.

## Not promoted by this release

- Model accuracy, operating thresholds, or deployment-domain calibration.
- Self-service claim corroboration as a production workflow.
- Versioned claim/license/catalog database entities.
- Durable leased workflow execution, outbox delivery, or Redis Streams.
- Production authentication, RLS, quotas, observability, or signed Evidence Statement v2.
- Legal conclusions, ownership determinations, training-data attribution, or universal style attribution.

See `V092_SEMANTIC_SAFETY_REPORT.md` for behavior matrices and remaining risks.
