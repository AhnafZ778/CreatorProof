# CreatorProof AI Rights Passport

Phase 1 stores an immutable, versioned record of a creator's preferences and
exports that record in useful formats. It keeps assertions, corroborated evidence,
contracts, and legal conclusions separate. Registering a work or recording
`ALLOW` does not establish ownership or grant a license.

## Record a policy

Use an API credential with `rights:write`. The work must exist in the credential's
tenant and must not have been deleted. If supplied, `creator_id` must identify a
creator profile or party in that tenant.

```http
POST /v1/works/{work_id}/rights-policy
X-API-Key: <your CreatorProof credential>
Content-Type: application/json
```

```json
{
  "AI_training_permission": "DENY",
  "commercial_training_permission": "LICENSE_REQUIRED",
  "style_reference_permission": "REVIEW",
  "attribution_required": true,
  "attribution_text": "Credit the registered artist",
  "license_required": true,
  "license_contact": "mailto:licensing@example.org",
  "minimum_license_fee": "25.50",
  "license_fee_currency": "USD",
  "geographic_scope": ["US", "DE"],
  "permitted_platforms": ["approved-platform"],
  "prohibited_models": ["unapproved-model"],
  "consent_status": "GRANTED",
  "consent_source": "creator-registration",
  "consent_timestamp": "2026-10-09T00:00:00Z",
  "creator_assertion_status": "SELF_DECLARED",
  "creator_assertion": {"source": "artist account"},
  "effective_from": "2026-10-09T00:00:00Z",
  "dimensions": {"asset_path": "/artwork/reference.png"}
}
```

Registration creates neutral version 1 with all permissions, consent, revocation,
and creator assertion status `UNKNOWN`. It asserts no creator identity and no
ownership. The baseline digest is bound into registration's existing signed
integrity event. A migration creates the same explicit baseline for older works
that have no policy; it does not fabricate historical signed events or consent.

Each submitted policy creates the next version (normally version 2 for the first
creator instruction). Omitted permission fields are `UNKNOWN`,
not inherited from the previous version. Send the complete intended policy when
revising a record. The server assigns the policy ID, version, canonical SHA-256
digest, creation timestamp, and caller identity; it records a signed integrity
event and an audit event. A concurrent version conflict returns `409` and can be
retried against the new current version.

Every permission accepts exactly `ALLOW`, `DENY`, `LICENSE_REQUIRED`, `REVIEW`,
`UNKNOWN`, or `NOT_APPLICABLE`:

| Permission field | Recorded preference |
| --- | --- |
| `search_indexing_permission` | Search indexing |
| `commercial_search_permission` | Commercial search |
| `AI_training_permission` | General AI training |
| `noncommercial_training_permission` | Noncommercial training |
| `commercial_training_permission` | Commercial training |
| `fine_tuning_permission` | Fine tuning |
| `style_reference_permission` | Use as a style reference |
| `image_to_image_permission` | Image-to-image use |
| `image_editing_permission` | AI image editing |
| `derivative_generation_permission` | Derivative generation |
| `likeness_use_permission` | Use of likeness |

The typed dimensions include attribution, licensing contact, fee and currency,
geography, permitted and prohibited platforms/models, and optional channels,
audiences and transformations. Country entries use two-letter uppercase codes or
`*`. Fees are decimal strings, avoiding floating-point changes. A fee requires a
currency. Overlapping permitted/prohibited entries, invalid preferences,
conflicting aliases, unknown fields, and invalid date ranges return `422`.

`creator_assertion_status` accepts `SELF_DECLARED` or `UNKNOWN`; the client cannot
declare itself a verified owner. Consent status is `GRANTED`, `NOT_GRANTED`,
`WITHDRAWN`, or `UNKNOWN`. A granted record requires source and timestamp.
Revocation status is `NOT_REVOKED`, `REVOKED`, or `UNKNOWN`; a revoked record
requires `revocation_timestamp`. Revoke by appending a new policy version; old
versions remain available for historical interpretation.

## Read and export

These authenticated GET routes require `rights:read`:

| Route below `/v1/works/{work_id}` | Result |
| --- | --- |
| `/rights-policy` | Current passport, evidence categories and export digest |
| `/rights-policy/{version}` | Specific recorded version |
| `/ai-preferences` | Structured preferences and standards adapter metadata |
| `/ai.txt` | Spawning-style text for publisher installation |
| `/tdm-policy` | TDM reservation projection and conditions |
| `/rights-statement` | Human-readable preference statement |

JSON responses distinguish `creator_assertion`, `verified_evidence`,
`contract_or_license`, `platform_policy`, `organization_policy`, and
`legal_conclusion`. Corroborated claims appear in verified evidence only after
their existing signed rights projection verifies. Unrecorded platform and
organization evidence and legal conclusions remain null.

The recorded policy digest covers the immutable policy fields; the GET export
digest covers the returned passport, including its current evidence projection.
Repeated reads with unchanged state produce the same canonical export digest and
ETag. Exports carry `Cache-Control: private, no-cache`. Effective state is one of
`ACTIVE`, `UNKNOWN`, `NOT_YET_EFFECTIVE`, `EXPIRED`, `REVOKED`,
`CONSENT_WITHDRAWN`, `CONSENT_NOT_GRANTED`, or `INTEGRITY_MISMATCH`. Historical preferences remain visible
as facts; inactive records cannot produce an affirmative export permission.

## Interoperability and publishing

The adapters are deliberately conservative when a target format cannot represent
the passport's conditions. Unknown values never become an opt-in. Geography,
platform/model restrictions, channel, audience, transformations, attribution,
license requirements and fees prevent a coarse unconditional `ALLOW` export.

- **Spawning ai.txt:** the export uses `User-Agent`, `Allow`, and `Disallow`
  directives for a supplied origin-relative `dimensions.asset_path`. Install the
  reviewed result at `/ai.txt` on the publisher's content origin. CreatorProof's
  authenticated export does not publish or automatically enforce it. Review the
  directive's path matching against the publisher's URL layout; absent paths or
  unrepresentable conditions generate explanatory comments without a broad
  allowance. See [Spawning's ai.txt documentation](https://site.spawning.ai/spawning-ai-txt).
  An unconditional allowance requires explicitly allowed general training,
  commercial training and fine tuning; unknown or conflicting fine-tuning
  preferences and a broad TDM reservation are never erased.
- **TDM Reservation Protocol:** the adapter references the [May 2024 W3C
  Community Group report](https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/).
  This is a community report, not a W3C Recommendation. A narrow training
  allowance cannot imply nonreservation of TDM generally. Broad nonreservation
  requires an explicit `dimensions.tdm_reservation: 0`; integer `1` records a
  broad reservation. Conditions or conflicting training/search denials or license
  requirements prevent an affirmative projection and produce `1`. A conflicting
  review preference or an inactive policy produces null. With no explicit broad
  preference and no recorded restriction, the result is null and the reservation
  header is omitted. The export preserves `recorded_tdm_reservation`, source JSON
  dimensions and `mapping_reason_codes` so the mapping remains inspectable. The internal policy URN
  is a `policy_identifier`, not a discoverable `tdm-policy` URL. No public policy
  URL or ODRL offer is invented. An operator must prepare and host a suitable
  public policy before adding a `tdm-policy` header on the content origin.
- **IETF AI preferences:** the adapter pins the [September 14, 2026 vocabulary
  draft](https://ietf-wg-aipref.github.io/drafts/draft-ietf-aipref-vocab.html).
  It is work in progress, and the API marks that status. Mappable `train-ai`,
  `search`, and `ai-use` categories use `y`/`n`; unresolved categories are omitted
  and listed separately. A category becomes `y` only when all mapped passport
  preferences are explicitly allowed and no conditions would be lost.
- **C2PA:** Phase 1's provider inspects provenance; it does not author or sign
  manifests. The usage assertion adapter returns `supported: false`,
  `UNSUPPORTED`, and a reason code. It does not fabricate deprecated
  training/mining assertions. The pinned [C2PA 2.3
  specification](https://spec.c2pa.org/specifications/specifications/2.3/specs/C2PA_Specification.html)
  records their removal. C2PA authoring requires a separate supported toolchain
  and signing/trust configuration.

## Use in scan policy decisions

The deterministic policy service evaluates the latest recorded preferences
alongside corroborated claims, signed license records, and evidence coverage.
The bound scan use context supplies `territory`, `channel`, `audience`,
`transformation`, `platform`, `model`, and optional `rights_permission`. Exact
known intended-use labels can also select the relevant permission.

An active `ALLOW` preference never creates license authorization. A scoped license
must also match the declared use and supplied context. Missing context on a
restricted dimension, an intended-use mismatch, expired/revoked policy, or an
unresolved relevant preference routes the finding to review. A `DENY` or prohibited
dimension is recorded explicitly. `BLOCK` still requires a confirmed reuse match,
complete required coverage, and the existing explicit organization policy that
blocks this rights condition. Style-only or incomplete findings do not become
automatic infringement decisions.

The server's neutral registration baseline records absence of instructions and
never authorizes a use. It also does not override an independently corroborated,
signed license whose scope permits the declared use. Explicit submitted
`UNKNOWN`/`REVIEW` instructions retain their review behavior; callers cannot label
their submitted policy as the server baseline.

## Share a redacted verification link

Issue `POST /v1/works/{work_id}/verification-token` with `works:write`, or
`POST /v1/scans/{scan_id}/verification-token` with `scans:write`:

```json
{"expires_in_seconds": 86400, "scopes": ["registration", "provenance", "rights", "evidence"]}
```

The four allowed scopes are also the default. Expiry is between 60 seconds and
365 days. The response returns a one-time raw token, token ID, expiration, and
`/verify/{token}` path. Persist the response securely if a link is needed; the
database stores only its SHA-256 hash. Public responses contain fixed, allowlisted
fields: an opaque public identifier, status, provenance summary, policy
version/digest/preferences, verification time, and a scan's recorded packet hash
and supported packet version when the `evidence` scope is enabled.

For a work, the rights summary reports the current work policy. For a scan, it
reports the immutable policy version/digest and effective state bound into that
scan's packet, marked `temporal_binding: AS_OF_SCAN`; appending a later work policy
does not relabel the old scan. Legacy packets without a usable bound policy
reference return a null rights summary rather than substituting today's policy.

Optionally configure `CREATORPROOF_PUBLIC_VERIFICATION_BASE_URL` with the trusted
public API origin, for example `https://api.example.org`. Issuance then also returns
an absolute `verification_url`. With an empty setting this field is null and the
relative path is returned. The setting rejects credentials, URL paths, query data
and fragments. HTTPS is required; development/testing may use a loopback HTTP
origin. Request `Host` headers never control the returned share URL.

Public verification excludes media, title, creator/contact identity, tenant IDs,
storage/source URLs, private notes, arbitrary provider results, and full packets.
It performs a minimal token lookup in a bootstrap session and then reads the
resource in a separate tenant-bound session. Token paths are masked in application
logs, access logs and metrics. Requests are rate-limited by client IP, including
requests with arbitrary API-key headers. Responses and errors use no-store and
no-referrer headers.

Revoke with `DELETE /v1/verification-tokens/{token_id}` using the corresponding
resource write permission or `rights:write`. Revocation is tenant-scoped and
idempotent. Revoked links return `410`; expired, unknown and deleted-resource
links return `404`. Issuance, access and revocation are audited without recording
the raw token. For multiple API instances, apply a shared IP rate limiter at the
gateway; the in-process limiter protects one instance.

## Validation

```bash
cd apps/api
.venv/bin/pytest -q tests/test_phase1_passports.py tests/test_phase1_policy_preferences.py tests/test_phase1_verification_middleware.py
```

These tests cover typed validation, export determinism, unknown/scoped permission
handling, policy expiry/revocation, signed license scope checks, tenant isolation,
public redaction and token lifecycle, IP admission control, and contribution
integrity. Frontend changes are outside this backend phase.
