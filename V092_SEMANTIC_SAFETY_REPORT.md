# CreatorProof v0.9.2 — semantic safety implementation report

Build: `SEMANTIC-SAFETY-SCOPE-2026.08.10`  
Date: 2026-08-10

## Outcome

CreatorProof now fails closed when it cannot prove that the declared catalog scope was fully checked.
The strongest customer-visible change is that coverage is no longer a hidden boolean: the API and UI
show eligible references, nominated candidates, verified candidates, omissions, capability execution,
catalog identity, and a committed snapshot digest.

This patch also closes three independent authority gaps:

1. Idempotency is bound to request content, not merely a caller-provided key.
2. AI-origin evidence has an explicit policy mode and defaults to informational.
3. Rights records cannot authorize use until their claim state is corroborated.

## Decision lattice

| Evidence condition | Match status | Maximum automatic outcome |
| --- | --- | --- |
| Verified exact/geometric copy with complete scope | `MATCH_FOUND` | Recorded rights policy, subject to corroborated claim |
| Verified copy with incomplete overall scope | `MATCH_FOUND` | `REVIEW` |
| Complete scope and no verified candidate | `NO_MATCH_IN_CHECKED_SOURCES` | `PASS_BY_POLICY` if required lanes are usable |
| Empty scope | `SCOPE_INCOMPLETE` | `REVIEW` |
| Partial verification | `SCOPE_INCOMPLETE` | `REVIEW` |
| Required retrieval degraded | `SCOPE_INCOMPLETE` | `REVIEW` |
| Candidate limit truncation | `SCOPE_INCOMPLETE` | `REVIEW` |
| Verification failure | `SCOPE_INCOMPLETE` | `REVIEW` |
| Ambiguous verified candidate | `INCONCLUSIVE` | `REVIEW` |

A positive verified match remains reportable under incomplete overall coverage because the system has
positive evidence for that specific reference, but incomplete scope still caps the policy action at
`REVIEW`.

## Coverage statement

Each completed packet now records:

- tenant, catalog, and membership-derived catalog version;
- full eligible manifest with exact hash, pHash, and learned-descriptor execution state;
- exact-hash and pHash execution counts;
- learned retrieval requirement and per-reference descriptor failures;
- whole-image and regional query counts;
- provider, model, and preprocessing identity;
- candidate limit, nominated IDs, verified IDs, failed IDs, and omitted IDs/reasons;
- typed coverage status and reason codes;
- SHA-256 snapshot digest and creation timestamp.

The compatibility boolean remains, but only `coverage_status` is authoritative.

## Idempotency behavior

The server reads and validates the candidate before replaying an idempotent request. It computes a
canonical digest from candidate SHA-256 plus normalized catalog and intended-use text.

| Request | Result |
| --- | --- |
| Same key, same canonical payload | Existing scan is returned |
| Same key, changed candidate bytes | Typed `409` |
| Same key, changed catalog | Typed `409` |
| Same key, changed intended use | Typed `409` |

The duplicate-commit race path performs the same digest comparison.

## AI-origin authority

| Mode | Execution | Policy authority |
| --- | --- | --- |
| `DISABLED` | OCR/model origin checks are deliberately skipped | None |
| `INFORMATIONAL` | Available checks run and remain visible | Cannot independently change policy |
| `REQUIRED` | Available checks run; unavailable/uncertain results are explicit | May route an otherwise allowed case to review |

Uncalibrated passive detector families may contribute review evidence but cannot combine into a
high-authority likely-AI classification. Missing or quiet evidence never proves human origin.

## Rights authority

`ASSERTED`, `DISPUTED`, `SUPERSEDED`, and `REVOKED` records cannot authorize use, even when the image
is an exact match and the record nominally says `EXISTING_LICENSE`. Only `CORROBORATED` can reach the
recorded-use pass path. The packet records the matched work ID, claim state, rights path, allowed uses,
intended use, coverage status, origin mode, and policy version.

The current UI can select claim states for demonstration, but this is not promoted as a production
corroboration workflow. The next data-foundation milestone must move that transition behind explicit
roles, immutable claim versions, evidence attachments, and audit events.

## Customer language

Customer-facing **creator-style attribution** language has been replaced with **creator-profile
resemblance**. Cohort statistics are named **catalog-relative empirical support** and explicitly state
that they are not conformal coverage, universal calibration, probability, copying, or infringement.

## Regression evidence

The 85-test backend suite covers:

- all six coverage states;
- complete-scope no-match gating and positive-match preservation;
- degraded learned retrieval and truncated verification;
- stable catalog version versus capability-sensitive snapshot digest;
- same-payload replay and changed-payload conflict;
- asserted and revoked claim denial plus corroborated authorization;
- disabled, informational, and required AI-origin modes;
- uncalibrated detector authority;
- high global similarity without geometry never becoming a match;
- existing geometry, style, proof, queue, runtime, and API invariants.

Ruff, TypeScript, and the optimized Next.js production build also pass.

## Remaining architecture risks

This patch deliberately does not disguise prototype boundaries:

- `Work` still combines asset, version, claimant, and rights metadata.
- Catalog versions are content-derived packet identities, not first-class relational versions.
- The local/Redis job system is not yet a durable leased workflow with an outbox and dead-letter path.
- API-key authentication, tenancy, retention, signing, observability, and migrations remain below a
  production SaaS bar.
- Model thresholds still require customer-domain, source-disjoint evaluation and promotion gates.
- Style profiles still group by claimant text and therefore remain experimental/advisory.

The next authorized milestone is the versioned relational and artifact foundation described in the
root `IMPLEMENTATION_PLAN.md`; model expansion should not outrun that foundation.
