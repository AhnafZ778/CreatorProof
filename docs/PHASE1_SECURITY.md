# Phase 1 security and privacy boundaries

The Phase 1 backend treats customer media, metadata, model output, and source descriptions as untrusted evidence. All private routes use API credential scopes and tenant filters; PostgreSQL additionally enforces tenant RLS. Public verification exposes a fixed safe projection via random, revocable tokens and must not expose contacts, raw candidate media, face embeddings, private source URLs, or internal provider payloads.

## Provider keys and logging

Keys remain in backend environment variables or a deployment secret manager. Settings exclude secret fields from repr and hide validation input values. Do not log settings dumps, credentials, HTTP provider request bodies, customer packets, raw media, or model output. Structured log redaction recursively handles nested dictionaries/lists and provider-specific key names, but it cannot rescue a secret deliberately interpolated into a free-form log message. Use identifier/state/duration fields only. Provider errors returned by the assistant contain bounded generic codes/messages; response bodies and authorization headers are excluded.

## External calls

AIand requests have bounded timeout, retry count, backoff, request/prompt size, streamed response size, JSON content type, and no redirects. Its configured endpoint must not contain embedded credentials, query strings, or fragments; production requires HTTPS. The operator-selected base URL is deployment configuration, never a URL accepted from an API caller. The circuit breaker is scoped to endpoint/model and local to the API process; use gateway quotas/shared controls for multiple replicas.

Marketplace image downloads already require provider host allowlists, allowed image content types, byte bounds, and disabled redirects. New backend endpoints do not expose arbitrary URL fetching. Egress firewall/proxy rules provide a second boundary against cloud metadata/private-network access. Refer to the existing webhook transport controls separately when enabling webhooks.

Official C2PA inspection is read-only and offline: both remote manifest fetching and OCSP fetching are disabled in temporary tool settings. The Linux subprocess adapter drains stdout and stderr in fixed chunks under a shared 8 MiB limit; binary version output has a separate 16 KiB limit. Overflow or timeout terminates the process group and returns an explicit error with unknown trust. JSON nesting/container budgets are checked before parsing; duplicate object keys, excessive numeric values, and malformed signature metadata cannot manufacture trusted results. Offline verification does not perform a fresh online revocation check. Deployments on other operating systems need an independently tested subprocess transport and reviewed binary pin.

## Assistant prompt and output boundaries

Only completed, stored scan packets and persisted scalar scan facts enter investigation requests. No browser prompt or arbitrary retrieval URL is accepted. Secrets, binary content, raw embeddings, and common private contact fields are removed; depth/item/text limits bound the JSON. Metadata strings remain quoted data, with marker characters escaped, and the system instruction tells the model not to execute them. Output is JSON with a fixed set of fields; unknown fields, missing/invalid types, unknown evidence/asset IDs, and newly invented URLs or ISO dates fail closed.

These checks reduce risk but do not verify every natural-language factual claim in a summary. General summaries cannot produce notice text. The admin notice path accepts only a structured plan containing supplied baseline paragraph indexes, then locally renders original facts and declarations without model-generated factual prose. Unknown fields/indexes, omitted/repeated sections, and noninteger indexes fail closed; model-supplied names, country, claimant authority, URLs, or dates cannot enter a notice through this plan. A human must still inspect the operator's claimant authority, license, specific copied region, source URL, jurisdiction, and notice declarations. The assistant cannot decide ownership/infringement, override policy, or deliver notices. A failed provider attempt persists its run/error state while evidence/policy remain intact. Investigations are not a legal opinion.

Provider content and output hashes are preserved. A one-time human disposition updates only the review marker; edited summary/notice text is stored as a separate append-only audit artifact bound to the original hash. Read/generation/review events are tenant scoped and retained for audit.

SQLite and PostgreSQL enforce immutable records through both application guards and database triggers. SQLite migration `0012` and `create_all` install update/delete and conflicting-insert guards on all 20 immutable evidence, provenance, rights, contribution, policy, review and transparency tables; this also blocks replacement writes such as `INSERT OR REPLACE`. Narrow exceptions permit only one complete human disposition, one external transparency commitment, or an evidence statement's legacy status projection, while preserving signed/generated content. Database/schema administrators can still change/drop guards; portable hashes/signatures permit independent integrity verification. Run the PostgreSQL migration/RLS verification separately before deployment.

## Media intake and retention

Existing accepted raster formats are JPEG, PNG, and WebP. Intake enforces upload bytes, image pixels, format verification, decoding, and decompression-bomb checks. Unsupported/corrupt media is rejected. This format whitelist is not a general malware scanner: isolate image/provider processes, keep codecs current, prohibit executable/archive/document uploads, and add an approved quarantine/scanner before accepting broader file types. Untrusted source metadata must never become shell arguments or executable instructions.

Candidate retention is explicit. With zero retention, candidate objects and derived candidate artifacts are deleted after completion, and a deletion receipt is kept. Read-only provenance reinspection cannot recover deleted media. Positive retention is enforced by startup/worker maintenance and a background sweep; expired media requests also refuse access and attempt cleanup. Failed storage deletion keeps its locator for retry and records a failure receipt. Private object access and a documented operator purpose remain required. Hashes can be retained as evidence references; they are not ownership proof.

Deletion receipts distinguish audit history from stored media: `requested_scope.immutable_history_retained` identifies retained history, `work_tombstoned` identifies a removed work, and `media_retained: false` records completed media removal. `objects_retained` contains actual storage deletion exceptions; retained database hashes/metadata are not presented as surviving image objects.

## Validation checklist

Run the Phase 1 assistant/security tests and existing authentication, tenancy, upload, storage, provider, queue, scan, policy, proof, and migration regression tests. Test missing provider credentials, malformed/oversized/redirect responses, request retry budget, circuit breaker, prompt-injection metadata, nested secret redaction, immutable output content, unauthorized access, and cross-tenant resource IDs. Run PostgreSQL RLS and migration tests against a configured instance before production; SQLite tests alone do not establish PostgreSQL enforcement.

Preflight separates configured credentials, locally verified binary identity, and live dependency connectivity. It never reports an uncalled remote provider as healthy. Keep Phase 1 frontend changes absent and preserve existing response fields; additions are backend-only.
