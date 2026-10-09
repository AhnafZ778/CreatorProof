# Stored artwork comparisons

Implemented on 2026-10-09. Admin opens **Stored cases**, a searchable gallery of
paired registered and observed images. Each card opens the existing review
workspace, with previous/next navigation, factual context, the Evidence Matrix,
and a previously prepared notice. The visual design uses the existing portal
colours, surfaces, fonts and controls.

## Ready to present

Open `http://localhost:3000/admin` and select a card:

- **Nocturne · full-image republication:** byte-identical artwork, US notice.
- **Tidal Garden · cropped publication:** a real crop match, EU notice.
- **Nocturne · AI sky edit:** a real match to the registered source, documented
  OpenAI image editing, and a UK notice.

Both originals were created programmatically for this project's collection.
The sky edit was actually generated from the Nocturne reference. All three
pairs passed the existing backend scan pipeline with `MATCH_FOUND`; match
scores, provider coverage and evidence were not fabricated. The editing record
contains the input/output hashes and generation artifact identity. Documented
editing history remains separate from detector findings.

The original and observed images have first-party collection pages under
`/collection`. These are actual registered artwork comparisons, not established
third-party infringements. Permission, claimant authority and jurisdiction
remain subject to operator review. Seeded contact details use a reserved
`.example` address, and no recipient is supplied. Prepared notices explicitly
identify unverified facts and proposed declarations. Nothing has been sent.

Opening the gallery, comparison, evidence and saved notice makes authenticated
read requests. No new scan, AI generation or review mutation is necessary.
Refreshing the page preserves the stored records. API and storage must remain
available; this is not an offline browser application.

## Persistence and deletion

Migration `0014_stored_case_comparisons` adds nullable `archive_record` to the
existing tenant-isolated review case. Candidate and reference bytes are copied
to a separate case prefix. Each copy is checked against its recorded SHA-256
before saving and again when served. Storage paths are not returned in gallery
responses. Raw scan evidence remains unchanged.

`CREATORPROOF_ADMIN_ARCHIVE_MATCHES=true` enables automatic capture of completed
registered-work matches while their candidate media is still retained. It is
enabled in the ignored local API configuration. The deployment example defaults
to false, and zero-retention mode never automatically saves comparison media.
An operator can also choose **Save this comparison** in the review inbox.

Stored comparisons remain until explicitly removed or the registered artwork
is deleted. Upload TTL cleanup removes the transient scan copy without removing
the explicitly archived case copy. Deleting the registered artwork includes all
associated comparison prefixes in its deletion receipt. Removing a comparison
keeps the scan's evidence and review history.

The current installation has three complete stored comparisons. Two earlier
matched scans had already lost their candidate media; those bytes cannot be
reconstructed. Their existing records were preserved.

## API and repeatable setup

- `GET /v1/admin/stored-cases?limit=200&offset=0`: tenant-scoped, paginated records,
  comparison endpoints, available prepared notice and stored context.
- `POST /v1/admin/stored-cases/{scan_id}`: idempotently save a completed match.
- `GET /v1/admin/stored-cases/{scan_id}/media/{candidate|reference}`: authenticated,
  hash-verified bytes with `private, no-store` caching.
- `DELETE /v1/admin/stored-cases/{scan_id}`: remove archived bytes and record the
  operator action. Read/write operations require their respective review scopes.

From `apps/api`:

```bash
PYTHONPATH=. .venv/bin/python scripts/migrate.py upgrade --revision head
PYTHONPATH=. .venv/bin/python scripts/preload_stored_cases.py --base-url http://localhost:3000
```

The migration helper made and verified a SQLite backup before upgrading the
current database. The loader is idempotent by reference hash and scan request
key, waits for real scan completion, and uses the real pipeline with offline
coverage recorded. Its isolated queue configuration prevents background webhook
delivery. It does not contact marketplace or AI inference providers, and it
does not run against production installations.

The later [measured ratings update](EVIDENCE_RATINGS_REPORT.md) supplies full
configured-model assessments for the saved comparisons. After preloading, run
`PYTHONPATH=. .venv/bin/python scripts/refresh_stored_assessments.py` from
`apps/api`. Unlike the original reduced-provider loader, this explicitly calls
configured inference providers, saves each assessment independently and links
it to the original case. Viewing the collection reads those saved results.

## Verification

The frontend contract/unit suite passed 70 tests. TypeScript and the production
build passed. Six read-only browser check groups verified paired files, AI edit
history, Evidence Matrix, prefilled notices, reload persistence, responsive
layouts, zero browser errors and zero API mutations during presentation.
Eight existing Artist/User/Admin workflow groups also passed after the update.

The full API regression suite passed (842 tests collected, with optional tests
skipped). New API tests cover independent image retention, idempotence, automatic capture,
zero-retention protection, hash mismatch rejection, artwork deletion and
cross-tenant isolation. Python lint and whitespace checks passed.

Screenshots: [gallery](assets/stored-cases/gallery-desktop.png),
[mobile gallery](assets/stored-cases/gallery-mobile.png),
[mobile comparison](assets/stored-cases/comparison-mobile.png), and
[prepared notice](assets/stored-cases/notice-desktop.png).

Repeatable browser check: `apps/web/scripts/stored-cases-browser.mjs`.
