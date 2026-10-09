# Evidence verdicts

Implemented on 2026-10-09 in the shared User/Admin Evidence Matrix.

The old cards displayed the union of all signal statuses. A supported artwork
match therefore appeared beside inconclusive retrieval rankings and unsupported
neighbors. Creator-profile signals always displayed `INCONCLUSIVE`, including
when their underlying model decision was more specific.

Each card now displays one assessment derived on the backend from the saved
model decisions, evidence and permission snapshot. Selecting a card opens its
explanation, available metrics, limitations and missing facts. Original signal
results and receipts remain accessible in a disclosure below the assessment.
An overall assessment separates supported findings from unresolved checks and
provides the next action.

## Verdict rules

| Evidence | Displayed finding |
| --- | --- |
| Completed match plus identical SHA-256 files | Exact copy confirmed |
| Completed match plus positive copy-fusion assessment | Visual reuse supported |
| Rejected neighbors or retrieval-only similarity | Cannot override a supported match or independently establish reuse |
| Complete checked scope with no supported match | No supported reuse found; limited to checked sources |
| Positive model result conflicting with final match decision | Reuse results need review |
| Completed origin ensemble | Its recorded AI classification, negative finding, disagreement or quality limitation |
| Missing origin/provenance provider | That check remains explicitly unassessed |
| Provenance inspection without credentials | No Content Credentials found; no stripping accusation |
| Learned high/very-high style finding with false-match control | Supported resemblance, separately from artwork reuse |
| Diagnostic style fallback, even with a high score | Diagnostic resemblance only |
| Matched artwork with an active permission conflict | Potential misuse: permission conflict |
| Matched artwork requiring a license without a recorded authorizing license | Potential misuse: required license missing |
| Matched artwork with a recorded authorizing license | Reuse has a recorded authorizing license |
| Matched artwork with unknown permissions | Reuse confirmed; authorization unverified |
| Incomplete coverage, failed scan or unresolved match | Further evidence and human review required |

Permissions must concern the supported artwork. Expired preferences cannot
establish a current permission conflict. A license and contradictory artist
preferences are surfaced as conflicting records. An absent recorded license,
AI-origin finding or stylistic resemblance alone never establishes infringement.
Potential misuse requires review of the actual published use, claimant authority,
outside permissions and applicable exceptions before enforcement.

## Existing records and integrity

`GET /v1/scans/{scan_id}/evidence-matrix` adds a versioned `assessment` object
alongside the original matrix, signals and coverage. This is a read projection
from the evidence packet and saved signal receipts. Existing cases receive it
immediately, without a migration, new inference call or a changed evidence hash.
Original matrix versions and publication decisions remain intact.

The three stored comparisons show one exact-copy finding and two supported
reuse findings. Their permission snapshots are unknown, so authorization remains
unverified. Their original reduced-provider runs remain immutable. The later
[measured ratings update](EVIDENCE_RATINGS_REPORT.md) runs the configured models
on the retained images, saves separate completed assessments and links their
actual measurements to each case with tenant, catalog and content-hash checks.
Current cards display those measured ratings and retain the original evidence.

## Verification

- 63 targeted API tests passed, including new assessment cases and existing
  evidence/provenance, permission-policy and frontend authorization tests.
- 18 model-bundle and health tests passed; the live API health and readiness
  endpoints returned 200 after refreshing the bundle's source revision.
- 70 frontend contract/unit tests, TypeScript and the production build passed.
- Five browser check groups verified all three stored cases, single verdicts,
  detailed metrics, original receipts, responsive layouts at 390/640/1024/1440px,
  zero browser errors and zero API mutations during presentation.
- Python lint, formatting and whitespace checks passed.

Browser captures: [desktop](assets/evidence-verdicts/desktop.png) and
[mobile](assets/evidence-verdicts/mobile.png).
