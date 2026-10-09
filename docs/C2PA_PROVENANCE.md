# C2PA and metadata inspection

CreatorProof extends its existing official `c2patool` adapter for local read-only inspection. No C2PA service key is needed. Inspecting a manifest does not create, embed, or sign one. Phase 1 does not present a self-signed certificate as trusted.

Primary references: [CAI open-source tooling](https://opensource.contentauthenticity.org/), [official c2patool usage](https://github.com/contentauth/c2patool/blob/main/docs/usage.md), [SDK context settings](https://opensource.contentauthenticity.org/docs/rust-sdk/docs/context-settings/), [C2PA specifications](https://spec.c2pa.org/specifications/), and [official c2pa-python](https://github.com/contentauth/c2pa-python).

## Configuration and network boundary

Use the existing `CREATORPROOF_C2PA_MODE`, binary path, timeout, expected version, and expected binary digest settings; see [provider setup](PHASE1_PROVIDER_SETUP.md). The preflight checks local identity and explicitly distinguishes an absent/unconfigured binary from a successful health check.

The reader passes local settings disabling remote-manifest and OCSP fetching. Uploaded manifest URLs must not become server-side fetches. Provider output is bounded and parsed defensively; malformed structures, excessive size/depth, invalid JSON, and timeouts produce explicit errors. A disabled remote trust lookup is not replaced by an invented trusted status. Production should additionally restrict process egress and keep the official tool/codecs current.

## States and evidence

| Persisted state | Meaning |
|---|---|
| VALID | Validation succeeds and signer trust is confirmed by the configured tooling |
| VALID_BUT_UNTRUSTED | Manifest validates but signer trust is not confirmed |
| INVALID | Manifest/signature validation reports failure |
| ABSENT | No manifest was found |
| UNSUPPORTED | Format/assertion inspection is unsupported |
| PROVIDER_UNAVAILABLE | Tool missing, disabled, unavailable, or timed out |
| PARSE_ERROR | Provider output could not be safely interpreted |

Legacy evidence packet states (`VALID_TRUSTED`, `VALID_UNTRUSTED`, `NOT_PRESENT`, `NOT_CHECKED`, `INVALID`, `ERROR`) remain compatible. Neither `ABSENT` nor `INVALID` determines human/AI origin.

Safe summaries retain manifest/claim-generator identity, validation reasons, declared creation/edit actions, model names where present, signing timestamp, ingredient relationships, parent references, thumbnail presence, manifest reference hash, C2PA version when supplied, and separate validity/signature/trust details. Assertions are declarations by a signer; they do not reveal the exact training image that influenced a model. Raw manifests, thumbnails, personal titles, and arbitrary source URLs are not returned publicly.

EXIF records presence/count and allowlisted software/device fields. IPTC records presence/count without personal fields. XMP uses a bounded XML parser and an allowlist; DOCTYPE/entity-bearing content is rejected. GPS, artist/contact/comment fields are omitted. `METADATA_ABSENT_NOT_PROOF_OF_REMOVAL` and `removal_status: UNKNOWN` avoid claiming deliberate stripping without comparison evidence.

## Persistence and APIs

Registered works are inspected at registration, reusing the origin gate's local inspection when available. Candidates are inspected during the evidence stage before retention cleanup. Records and ingredients are tenant-scoped and immutable, with input hash, provider identity/version, normalized/legacy status, reasons, safe summaries, and processing time. Failed attempts can be retried as additional records; successful identical projections are reused.

Authenticated routes under `/v1`:

- `POST /works/{work_id}/provenance/inspect` (`works:write`) and `GET /works/{work_id}/provenance` (`works:read`).
- `POST /scans/{scan_id}/provenance/inspect` (`scans:write`) and `GET /scans/{scan_id}/provenance` (`scans:read`).

Reads return the latest safe record and ingredients and create evidence-access audit events. Reinspection needs retained media; missing/expired candidate media returns 404 while persisted summaries remain available. Deleted works lose active access and retain immutable history only as explicitly documented in deletion receipts.

## Verification limits

Contract tests cover valid/trusted/untrusted, invalid signature, absent, unsupported, malformed output, multiple ingredients, AI-generated/edited declarations, metadata safety, and provider failure. A real local binary identity/no-manifest smoke check is a separate verification. Mocked fixtures do not prove certificate trust, OCSP status, or every C2PA assertion/version in production. See the final implementation report for the actual checks performed.
