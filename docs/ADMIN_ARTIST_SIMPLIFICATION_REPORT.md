# CreatorProof: focused Artist and Admin workspaces

Implemented on 2026-10-09. This update simplifies the existing frontend and makes
completed User flags available for human review in Admin.

## What changed

Admin has three sections:

- **Review inbox:** one record per flagged scan, with search, pending/all-flags
  filters and pagination. Opening a record reveals three tools: **Review &
  decide**, **Detailed evidence**, and **Prepare notice**.
- **Monitoring:** source, query and artist catalog, followed by the latest new
  discoveries. Extra monitoring options start collapsed. Provider checks begin
  one minute after Start and repeat one minute after each completed check;
  pausing stops subsequent checks. Monitoring continues while this Admin page
  stays open, including when another section is selected.
- **History:** saved source records, with artwork-match and match-with-AI-indicator
  filters and access to older pages. A scan can be opened from its saved photo.

Duplicated overview cards and separate lists of the same case/detection were
removed. Notice forms, evidence tools and the optional AI assistant no longer
fill the initial inbox. Each record keeps its actual scan, evidence and review
case, rather than creating a second flag when it also came from a marketplace.

Artist has **Artwork library** and **Register artwork** views. Registration shows
only the reference, title and claimant first; catalog and claim settings are in
Advanced registration settings. Selecting a library artwork opens **Permissions**,
**Creation history**, **Origin evidence**, and **Share & export**. Permission
categories and advanced licensing, scope, dates, history and withdrawal controls
are grouped in disclosures. Switching tools preserves their unsaved state.

Both workspaces use the existing portal fonts, surfaces, accents and controls.
Tabs support arrow keys, Home and End. Mobile layouts fit without horizontal
scrolling.

## User-to-Admin workflow

1. Register the reference in Artist and note its catalog.
2. In User, choose the candidate, the same catalog and intended use. Optionally
   supply the exact public image/page URL and a notice-country declaration.
   Publication country, channel, audience and other intended-use fields remain
   separate optional details.
3. Run the scan. A completed flag shows **Saved for Admin review** only after the
   server confirms it is saved. **Open review** links to that exact scan in Admin.
4. Admin opens the record and sees the flag reasons, retained candidate and
   reference images, artist/claimant, artwork, catalog, declared use, country
   basis, public source, policy outcome and available rights information.
5. Inspect Detailed evidence if needed, then record an attributable approval,
   rejection, license-needed or escalation disposition. Resolved records remain
   available under All stored flags.
6. For a supported registered-work match, open Prepare notice, confirm claimant
   authority/contact and both exact public URLs, choose the jurisdiction and
   generate a saved draft. Review and copy the text or prepare an email handoff.
   A recipient and human-review checkbox are required for email. The operator
   chooses whether to send through the recipient's official channel.

The inbox also includes inconclusive copying evidence, AI-origin indicators,
actual learned creator-resemblance flags, and policy REVIEW/BLOCK outcomes.
Assessment gaps have their own category and do not allege copying. Clean results
and unsupported indicators do not become content findings. Filtering occurs
before pagination, so unrelated clean scans cannot hide older flags.

Country declarations do not establish anyone's residence. Marketplace source
information remains authoritative for its listing URL; eBay item location is
shown separately and does not locate the seller. Missing information stays
explicitly missing.

## Persistence and safeguards

The existing local API configuration now retains newly submitted candidates for
seven days (`CREATORPROOF_CANDIDATE_RETENTION_SECONDS=604800`) so Admin can compare
them visually. Saved evidence remains after media expiry. Already deleted
candidate files cannot be restored. The default zero-retention mode and its
privacy behavior remain supported and tested.

Saved drafts can be retrieved without another inference request. Reopened drafts
are available for reading/copying; email handoff requires generating a draft
from the currently confirmed form context. This prevents a stored notice from
being handed off using unrelated or incomplete form URLs.

A copyright draft requires a completed real catalog match and an available
registered work. Authorized uses, publication-approved resolved cases, AI-only
flags and assessment gaps cannot create copyright notices. Historical flags can
open a review case idempotently. Tenant-scoped reads, guarded mutations and
finite authenticated media proxies remain in place.

Changing selected records resets case-owned claimant/notice fields and pending
state. Late decisions and draft responses cannot overwrite a different selected
record. Pagination has its own request lock and preserves older loaded records
through automatic refreshes. Notice drafting uses the existing AI & Inference
integration with deterministic fallback; this update does not send any notice.

## Verification

- The complete API test suite passed, with optional tests skipped. Follow-up
  tests passed for flags, health/model-bundle identity, retained/expired media,
  signed context, notice restrictions and pagination past 200 stored photos.
- 69 frontend contract/unit tests passed; TypeScript and production build passed.
- Eight real API/browser workflow groups passed: Artist registration, User saved
  receipt, Admin comparison/context, detailed evidence, drafting/email gating,
  saved notice reload, recorded decision/history, and responsive layouts.
- Seven eBay browser regression groups passed, including the initial 60-second
  delay, repeated checks, deduplication, pause, provider errors and mobile layout.
- The focused Artist browser checks passed for the grouped tools and responsive
  views. Browser workflow tests used isolated fixtures and no live inference or
  marketplace calls.

Screenshots: [Admin desktop](assets/admin-workflow/admin-comparison-desktop.png),
[Admin mobile](assets/admin-workflow/admin-comparison-mobile.png),
[Artist desktop](assets/admin-workflow/artist-desktop.png), and
[Artist mobile](assets/admin-workflow/artist-mobile.png).

The repeatable workflow fixture is
`apps/web/scripts/admin-workflow-fixture-api.py`; its browser driver is
`apps/web/scripts/admin-workflow-browser.mjs`.
