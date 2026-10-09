# Admin review, monitoring and notices

Apply migrations before starting an API with the Phase 1 tables:
`cd apps/api && PYTHONPATH=. uv run python scripts/migrate.py upgrade --revision head`.

Open `/admin`. **Stored cases** is the default section. Select an image pair to
open its comparison, evidence and saved notice without scanning again. Artwork
copies and documented AI edits have separate filters. The preloaded collection
uses project-owned originals and first-party publication pages; permission and
authority still require review. See the [stored-case report](STORED_CASES_IMPLEMENTATION_REPORT.md).

**Review inbox** contains completed flagged uploads
and marketplace scans appear once per scan. Search or switch between Needs
review and All stored flags; Load older flags reveals earlier records.

Open a record to see **Review & decide**, **Detailed evidence**, and **Prepare
notice**. The first view shows the image comparison, reasons, artist/reference,
intended use, catalog, country declaration, public source and rights details.
Record an approval, rejection, license-needed or escalation disposition after
reviewing the facts. Escalation records that further review is needed; it does
not deliver the case to another person. Resolved records remain stored.

User uploads may include an optional country declaration and public page/image
URL. These are bound to the saved scan. Country is separate from intended
publication territory and is not proof of residence. Copy matches, inconclusive
copy evidence, AI indicators, learned resemblance and policy review/block flags
reach Admin. Assessment gaps are labeled separately, without a misuse allegation.
Clean scans do not require an Admin decision.

Submitted images follow `CREATORPROOF_CANDIDATE_RETENTION_SECONDS`. The current
local configuration retains new candidates for seven days so the comparison can
be viewed. Old deleted files cannot be recovered; saved evidence survives expiry.
With `CREATORPROOF_ADMIN_ARCHIVE_MATCHES=true`, completed registered-work matches
also save both comparison images to a separate case archive. Archived pairs
survive upload expiry and remain until removed or their registered artwork is
deleted. Zero-retention mode does not create automatic archives. **Save this
comparison** captures an available pair manually.

For a supported registered-work match, open **Prepare notice**. Confirm claimant
authority and contact, the protected work and its public URL, and the exact
flagged public location. Select US DMCA, EU DSA, UK, Canada, Australia or the
international template. The server saves the draft with its generation provider
and model. Authorized/publication-approved uses, deleted references and
AI-only/assessment-gap cases do not qualify for copyright drafting.

AI & Inference is configured only on the API server with
`CREATORPROOF_AIAND_API_KEY`, `CREATORPROOF_AIAND_BASE_URL` and
`CREATORPROOF_AIAND_MODEL`. It receives recorded facts and a deterministic
jurisdiction checklist. Provider failure falls back to a saved template.

**Saved notice drafts** retrieves earlier text without inference. Reopened drafts
are read-only and can be copied. Generate a notice from the currently confirmed
form context to use email handoff. **Open notice in email** requires both public
URLs, a recipient and the review checkbox. It records the handoff and opens the
operator's mail client; the operator decides whether to submit through the
recipient's official copyright or DSA channel.

**Monitoring** contains provider, search and catalog settings. Use the catalog
that contains the artist's references. Start monitor waits 60 seconds before the
first provider request, then checks again 60 seconds after each completed check.
It stays active while this Admin page remains open, including while viewing
other sections. Pause monitor stops future requests. Repeated provider/external
IDs remain in history and do not appear as new discoveries.

**History** shows saved source photos with filters for artwork matches and
matches with AI indicators. Load older history accesses records past the first
200. These classifications are review signals; a person owns the final action.

The eBay selector identifies sandbox/production. Sandbox history IDs include the
environment and marketplace. Listings without photos are omitted; item location
does not establish seller residence. See the [connector guide](MARKETPLACE_CONNECTORS.md)
and [workspace report](ADMIN_ARTIST_SIMPLIFICATION_REPORT.md).

**Detailed evidence** now shows measured copy, AI and style indices alongside
the license count, recorded policy, references checked and verified packet hash.
The three stored comparisons have full saved model assessments; opening them
does not run detection. Scores keep their named units, with provider details
and limitations available in the signal disclosure. See the
[ratings report](EVIDENCE_RATINGS_REPORT.md) for measured results and refresh steps.
