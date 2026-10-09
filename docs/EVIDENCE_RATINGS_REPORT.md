# Measured evidence ratings

Implemented on 2026-10-09 in the shared User/Admin Evidence Matrix. Cards now
show a measured value, its unit, a specific finding and a visual scale where
appropriate. The headline confirms exact copying or validated artwork reuse
when supported by the saved match assessment. Detailed model decisions,
limitations and original receipts remain available below each card.

## Current saved comparisons

The configured pipeline was actually run on all three retained image pairs.
Sightengine's primary request succeeded for each current assessment; local
SSCD/CSD matching and the official C2PA tool also produced saved results.

| Comparison | Copy evidence /100 | AI detector /100 | Style similarity /100 | Reuse finding |
| --- | ---: | ---: | ---: | --- |
| Nocturne, full-image republication | 100.0 byte identity | 0.1 | 81.5 | Exact copy confirmed |
| Tidal Garden, cropped publication | 90.6 | 0.1 | 77.8 | Registered artwork reuse confirmed |
| Nocturne, AI sky edit | 89.8 | 99.0 | 69.6 | Registered artwork reuse confirmed |

All three checked **2 / 2 registered references** in their declared catalog.
All three current assessment packets pass a freshly recomputed SHA-256
commitment check. All three permission snapshots contain **0 authorizing
licenses on record** and a saved publication decision of **REVIEW**, requiring
operator approval. These are concrete recorded facts, not a claim that an
external license cannot exist or that infringement has been established.

Original and cropped images have **0 embedded Content Credentials found**.
The AI-edited file's credential validation is **Valid**, with **Signer untrusted**
explicitly displayed. The adapter previously misclassified the successful
`claimSignature.insideValidity` result as a signature failure; it now recognizes
that success code while preserving actual failure codes and untrusted signer
states. This follows the [official C2PA validation specification](https://spec.c2pa.org/specifications/specifications/2.3/specs/C2PA_Specification.html).

## Meaning of ratings

- Byte identity is a deterministic exact-file match.
- Copy and style scores retain their model indices, scaled to /100 for display.
- The AI score retains the actual detector ensemble output. A strong vendor
  signal is distinct from calibrated origin certainty. Calibration, family
  coverage and transformation limits remain available in the detailed finding.
- Permissions show a count or recorded conflict, rather than an invented score.
- Policy shows the actual PASS, REVIEW or BLOCK decision.
- Coverage counts registered references checked, not the entire internet.
- Integrity verifies packet commitment; it does not establish ownership.

None of these indices is presented as a probability of infringement. Missing,
failed or invalid measurements remain explicit and never become a zero score
or a positive verdict. The backend returns `display`, `label`, `grade`, `value`,
`scale`, `basis`, `conclusive` and `tone` for each lane.

## Persistence and refresh

The original case scan, immutable packet, matrix, signals and archived images
remain intact. A separate completed scan supplies the full model assessment.
Its link is accepted only within the same tenant and catalog, with matching
candidate bytes, registered work/reference hashes and a verified packet hash.
If any binding fails, the API falls back to the original case assessment.

`GET /v1/scans/{id}/evidence-matrix` retains the original fields and adds
`assessment_signals` and `assessment_source` to identify the current measured
assessment. Opening a case reads saved results; it performs no inference,
decision, notice generation or handoff.

From `apps/api`, prepare assessments after preloading the collection:

```bash
PYTHONPATH=. .venv/bin/python scripts/refresh_stored_assessments.py
```

The script uses configured real providers and credentials, refuses production,
disables webhook delivery in its isolated inline environment and records an
`ASSESSMENT_REFRESHED` review event. Request keys make repeat execution
idempotent. It does not change match thresholds or permissions.

A later AI-edited assessment encountered an operational Sightengine timeout.
Its fallback run and results were retained. An explicit reassessment with a
longer bounded timeout completed successfully and now supplies that case:

```bash
PYTHONPATH=. .venv/bin/python scripts/refresh_stored_assessments.py \
  --revision v3-provider-timeout-retry --comparison-kind AI_EDIT \
  --sightengine-timeout-seconds 60
```

Reassessment is an operator action. It is never triggered while presenting the
Admin collection. Live scans continue to honor provider failures and native
review/abstention decisions.

## Verification

- Targeted API rating, provenance, assessment and health tests passed.
  New cases protect missing/invalid scores, packet tampering, unsuccessful
  scans and candidate/catalog/work/reference/tenant binding failures.
- Signature-validity tests preserve failure-bucket precedence and signer trust.
- 70 frontend tests, TypeScript and the production build passed.
- Five read-only browser check groups verified all three current saved
  assessments, exact frontend/API measurement agreement, aligned cards,
  detailed receipts, reload persistence and layouts at 390/640/1024/1440px.
- Browser presentation produced zero page errors and zero API mutations.
- Python lint, formatting and whitespace checks passed.

Captures: [desktop](assets/evidence-ratings/ratings-desktop.png),
[mobile](assets/evidence-ratings/ratings-mobile.png) and
[browser verification](assets/evidence-ratings/verification.json).
Repeatable browser check: `apps/web/scripts/evidence-ratings-browser.mjs`.
