# Phase 1 provider setup

Phase 1 runs locally with SQLite, private filesystem storage, and the local job queue. C2PA inspection, AI origin detection, AI investigation drafting, and marketplace search are optional capabilities with explicit unavailable states. No wallet, gas, email provider, or automatic notice submission is needed.

## 1. Configure the backend locally

From the repository root, use `.env.example` as the reference for `apps/api/.env`. Preserve existing local values; do not overwrite an already configured file. Keep provider keys only in this ignored backend file or a secret manager. For Docker Compose, its interpolation file is the root `.env`; API/worker receive the provider variables, while the web service receives none of these provider keys.

The repository intentionally preserves the existing `CREATORPROOF_AIAND_*` names rather than requiring a second, conflicting set of `AI_INFERENCE_*` settings.

Run from `apps/api`:

```bash
uv sync --locked
uv run python -m scripts.phase1_preflight
```

The repository-root wrapper runs the same backend environment/configuration: `python3 scripts/phase1_preflight.py`.

This prints JSON and never prints keys. `CONFIGURED_NOT_LIVE_CHECKED` means a credential is present; it does not mean the endpoint is reachable or the credential is accepted. C2PA's local binary identity is checked without media. Optional unavailable capabilities do not fail the default preflight.

To require particular optional capabilities:

```bash
uv run python -m scripts.phase1_preflight --require c2pa --require assistant
```

After database initialization, `--live` performs read-only database `SELECT 1` and Redis `PING` when selected. It does not upload media, run AI models, send notices, create a SQLite database, or spend remote provider quota. A successful dependency probe is connectivity evidence only; startup and migration checks still validate schema/RLS.

```bash
uv run python -m scripts.phase1_preflight --live
```

Exit codes are `0` for a valid configuration with its requested optional requirements met, `2` for settings validation failure, and `3` for unavailable required capability or failed dependency check. The existing model-bundle identity report is included separately; use `scripts.preflight_part1 --require-state ...` for its qualification gate.

The account and permission guidance below was checked against public provider documentation on 2026-10-09. Dashboard availability, granted model access, quotas, and the price for your account still require an operator check. No remote credential or billable provider request was validated by that documentation review. Check configuration through the preflight rather than printing an environment file or key.

For routine rotation, create a replacement credential, save it to the backend/deployment secret store, restart both API and worker, and validate the affected capability with permitted test data. Revoke the previous credential at the provider after that check. If a key was exposed, revoke it immediately and use the documented unavailable/fallback behavior during replacement. Removing a local key or changing a login password does not establish provider-side revocation.

## 2. C2PA / Content Authenticity Initiative

Read-only inspection needs no API key or paid account. CreatorProof already uses the official `c2patool` subprocess adapter, so Phase 1 retains it. See the [official CAI tooling](https://opensource.contentauthenticity.org/) and [c2pa-rs/c2patool releases](https://github.com/contentauth/c2pa-rs/releases).

Set:

```dotenv
CREATORPROOF_C2PA_MODE=auto
CREATORPROOF_C2PA_BINARY=c2patool
CREATORPROOF_C2PA_EXPECTED_VERSION=0.27.7
CREATORPROOF_C2PA_TIMEOUT_SECONDS=20
```

Install the selected release for the deployment architecture, then pin `CREATORPROOF_C2PA_EXPECTED_BINARY_SHA256` to the artifact's independently checked SHA-256. The example digest belongs to the repository's selected Linux binary; a different platform requires its own reviewed digest. Do not disable the digest/version checks to make an unexpected binary pass. The standard API image does not bundle this optional executable: build a deployment image containing the pinned official binary or expose its installed path to API/worker.

A manifest may be valid but untrusted. An absent manifest supplies no human-authorship conclusion; an invalid manifest supplies no AI-generation conclusion. Read-only Phase 1 does not sign media. Later trusted signing requires a suitable certificate/trust path and KMS/HSM-backed private keys; self-signed development credentials must not be labeled trusted. See [C2PA Python key-handling guidance](https://github.com/contentauth/c2pa-python/blob/main/docs/usage.md).

The saved [local inspection smoke report](../apps/api/benchmarks/phase1/c2pa_local_smoke.json) uses a generated unsigned PNG with identical bytes under `.png` and storage-like `.bin` names. The pinned local tool reports `ABSENT` for both and `PARSE_ERROR` for a corrupt fixture, with unknown signature/trust and no implied human origin. This exercises actual inspection, beyond the preflight identity probe. It does not qualify trusted, tampered, signed AI assertion or ingredient-chain fixtures; those still require reviewed credentials/fixtures.

## 3. Sightengine

Create or sign in to a Sightengine account, then open the [API credentials page](https://dashboard.sightengine.com/api-credentials). It supplies the API user ID and secret pair described in the [official credential instructions](https://sightengine.com/faq/get-my-credentials). Set them locally:

```dotenv
CREATORPROOF_SIGHTENGINE_API_USER=
CREATORPROOF_SIGHTENGINE_API_SECRET=
CREATORPROOF_SIGHTENGINE_TIMEOUT_SECONDS=20
CREATORPROOF_SYNTHETIC_DETECTOR=auto
```

The existing integration uploads the accepted image to the `genai` model. Confirm that this external processing fits your data policy before exercising it with customer media. See the [official AI image detection contract](https://sightengine.com/docs/ai-generated-image-detection). For a deployment that must never construct local model fallbacks, select `sightengine_only`; an outage then remains unavailable. With `auto`, any existing local fallback is recorded separately in coverage and must not be represented as a healthy vendor result.

Use credentials dedicated to backend image analysis; this integration needs neither account administration nor content publishing. Public documentation does not establish configurable per-key read-only/model scopes or a specific self-service rotation/revocation control. Confirm available restrictions and replacement/revocation with the credentials page or provider support; do not assume those controls exist. Sightengine publishes a [free testing plan and paid plans](https://sightengine.com/pricing); available models, quotas, and the selected account's charges must be checked before live scans.

Validate an actual provider response with one authorized, creator-owned image through the normal scan API, then inspect origin provider/coverage/reason codes in its packet. A provider score is origin evidence only and does not prove copying, infringement, or influence from a particular training image.

## 4. AI & Inference investigation assistant

Sign in to the [AI & Inference console](https://console.aiand.com), select the intended organization, and use Settings → API Keys → Create, as documented in [organization API keys](https://docs.aiand.com/organizations/api-keys/). Store the one-time-displayed key in the backend secret store. The configured endpoint remains the user-selected [AIand endpoint](https://api.aiand.com/v1), with the model preserved:

```dotenv
CREATORPROOF_AIAND_BASE_URL=https://api.aiand.com/v1
CREATORPROOF_AIAND_API_KEY=
CREATORPROOF_AIAND_MODEL=deepseek-ai/deepseek-v4-flash
CREATORPROOF_AIAND_TIMEOUT_SECONDS=30
CREATORPROOF_AIAND_MAX_ATTEMPTS=2
CREATORPROOF_AIAND_RETRY_BACKOFF_SECONDS=0.25
CREATORPROOF_AIAND_RESPONSE_MAX_BYTES=524288
CREATORPROOF_AIAND_PROMPT_MAX_CHARS=120000
CREATORPROOF_AIAND_CIRCUIT_BREAKER_FAILURES=5
CREATORPROOF_AIAND_CIRCUIT_BREAKER_COOLDOWN_SECONDS=60
```

A dedicated organization key is sufficient for inference; the provider documents a [member role that can run inference and manage its own keys](https://docs.aiand.com/organizations/members/). A runtime process needs no owner/admin login or management JWT. Keys bind billing to one organization without an extra `X-Org-ID` inference header. Public docs do not describe configurable per-model/per-endpoint scopes, so do not promise a read-only key. Inference consumes [prepaid, per-token credits](https://docs.aiand.com/models/pricing/); current model prices, currency, credit availability, and access are account-specific, with no free credit assumed.

The client sends OpenAI-compatible `POST /chat/completions` with `response_format: {"type":"json_object"}` for investigations. The provider documents [structured outputs](https://docs.aiand.com/capabilities/structured-outputs/), but acceptance by the selected model/account and CreatorProof's strict response validation still require an authorized live call. If it rejects structured output, do not silently parse arbitrary prose as an investigation. Record the unavailable run and keep deterministic evidence/policy intact. Confirm model access and request limits in the provider account if unclear.

Rotate by creating and deploying a replacement key, then revoking the old key. The documented management API revokes with `DELETE /api/v1/keys/{key_id}` and requires an operator's JWT plus `X-Org-ID`; never give those administrative credentials to CreatorProof. Console-created keys do not automatically expire, and removing a member does not revoke that member's existing keys. See the [provider's rotation/revocation contract](https://docs.aiand.com/organizations/api-keys/).

Backend workflow:

1. Complete a normal scan.
2. Call `POST /v1/investigations/scans/{scan_id}` with a credential holding `review:write`.
3. Read `GET /v1/investigations/{run_id}` with `review:read`. Review summary, references, missing facts, suggested steps, and contradictions. General scan summaries keep `factual_notice_draft` null because the scan does not establish claimant authority or legal declarations.
4. Call `POST /v1/investigations/{run_id}/decision` with `ACCEPTED`, `EDITED`, or `REJECTED`. `EDITED` requires `edited_summary` or `edited_notice`. Human edits form an append-only audit artifact, while the generated content/hash stay preserved.

Each run records provider, model, prompt version, authoritative evidence-packet commitment, separate minimized provider-input/context hash, output hash, and timestamps. The evidence commitment uses the repository's existing scope `CANONICAL_EVIDENCE_PACKET_EXCLUDING_PROOF_OBJECT`; provider input may add persisted scalar facts or notice-layout context without changing that original commitment. A mismatch with the packet's recorded hash fails closed. Failed attempts are saved. Reviews record human identity, disposition, original output hash, and a separate review hash. This endpoint never changes deterministic scan policy or sends/submits a notice.

The existing admin notice endpoint remains backward compatible. With a completed stored scan packet, AI assistance uses a strict JSON plan of baseline paragraph indexes. The backend renders every paragraph once from the deterministic jurisdiction notice, preserving operator-supplied facts, declarations, contact details, and checklist. The model cannot introduce new names, country, authority, dates, or URLs in that notice. Contact emails are redacted before sending paragraphs to the provider. The result gets its own hash-bound investigation output; the saved draft returns additive `investigation_output_id`. Unscanned discoveries and unavailable/invalid provider plans retain the deterministic template fallback. No notice is delivered by these endpoints.

Test environments intentionally disable live provider usage, even if a developer `.env` contains a key. Unit tests use mocked HTTP responses; integration tests use a mocked assistant result. Model wording still requires human verification; JSON and URL/date/reference checks do not turn prose into verified legal facts.

## 5. Database, queue, and storage

Local development needs only:

```dotenv
CREATORPROOF_DATABASE_URL=sqlite:///./creatorproof.db
CREATORPROOF_STORAGE_PROVIDER=local
CREATORPROOF_STORAGE_ROOT=./data
CREATORPROOF_JOB_BACKEND=local
```

Use `uv run python -m scripts.migrate upgrade` for migration-managed databases. The Compose setup supplies PostgreSQL 17 and Redis 7 locally; no paid service is needed. Start only backend services if the frontend must remain outside the phase:

```bash
docker compose up -d postgres redis db-init migrate api worker
docker compose exec api uv run --no-sync python -m scripts.phase1_preflight --live
```

PostgreSQL migration owner and application runtime roles are deliberately separate. Do not give the runtime role table ownership, superuser, or `BYPASSRLS`. Production startup verifies tenant RLS. Existing [deployment guidance](BLOCKCHAIN_IMPLEMENTATION_AND_DEPLOYMENT.md) describes this split; its blockchain credentials are optional outside Phase 1.

For the supplied Compose development database, set `CREATORPROOF_POSTGRES_OWNER_PASSWORD` and `CREATORPROOF_POSTGRES_RUNTIME_PASSWORD` in root `.env`; these are Compose bootstrap inputs, not backend Settings fields. `CREATORPROOF_MIGRATION_DATABASE_URL` and `CREATORPROOF_RUNTIME_DATABASE_URL` select the separate Compose connection URLs. A managed PostgreSQL account/dashboard is your deployment's choice: obtain database/host/TLS details and provision the runtime role before setting backend `CREATORPROOF_DATABASE_URL`. The runtime role needs the application's table/sequence access, not a read-only role, because scans and review events are persisted. PostgreSQL itself needs no vendor API key; hosted pricing and account controls are provider-specific. Rotate the role password using a secured `psql` session's `\password`, then update secrets and recycle connections. To revoke access, an administrator can disable role login and close existing sessions; disabling login alone leaves established sessions alive. See [PostgreSQL role management](https://www.postgresql.org/docs/17/sql-alterrole.html).

Redis authentication, if selected, belongs in `CREATORPROOF_REDIS_URL`; use a dedicated ACL username/password and TLS (`rediss://`) for a remote deployment. An example hosted option is [Redis Cloud database creation](https://redis.io/docs/latest/operate/rc/databases/create-database/) with [database passwords/RBAC](https://redis.io/docs/latest/operate/rc/security/access-control/data-access-control/); the selected plan's costs and TLS availability need confirmation. Runtime queue permissions include reads and writes for the configured queue/stream, consumer group and lease operations; `PING` alone cannot qualify them. Restrict keys/commands using [Redis ACLs](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/), and exclude account/server administration. Rotate by adding a replacement ACL password or dedicated user, updating API/worker and reconnecting, then removing the old password/user. [Deleting an ACL user](https://redis.io/docs/latest/commands/acl-deluser/) also closes its connections. The supplied local Compose Redis uses its private development network without authentication; a hosted/authenticated Redis URL requires a Compose override for API/worker, since the base file fixes their local URL. The `local` queue remains the no-account fallback.

Optional durable storage uses the existing S3-compatible adapter. Set `CREATORPROOF_STORAGE_PROVIDER=s3`, `CREATORPROOF_S3_BUCKET`, `CREATORPROOF_S3_REGION`, `CREATORPROOF_S3_ENDPOINT_URL` if needed, `CREATORPROOF_S3_ACCESS_KEY_ID`, and `CREATORPROOF_S3_SECRET_ACCESS_KEY`. This adapter's settings validation requires the key pair. Use a private bucket; runtime storage needs read/write/delete for uploads and retention, not read-only credentials. Limit AWS object permissions to `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` within the selected bucket/prefix, and `s3:ListBucket` for the necessary prefix listing; add encryption-key access only if the bucket requires it. Bucket/account administration belongs to the operator. See [S3 permissions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-management.html).

With AWS, an authorized IAM user creates keys under Security credentials → Access keys; replace the key, verify use, then deactivate/delete the old one through the [documented IAM access-key controls](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-key-self-managed.html). Do not use root-account keys. With Cloudflare, enable R2 in the account, open R2 Object Storage → Manage API Tokens, and create a token granting Object Read & Write only to the required bucket(s); save its S3 key pair. See [R2 token setup and permissions](https://developers.cloudflare.com/r2/api/tokens/). Issue a replacement token, deploy/test it, and revoke the previous token in the provider account; confirm the account's available revocation controls. Storage/request charges are deployment/account-specific; consult [AWS S3 pricing](https://aws.amazon.com/s3/pricing/) or [R2 pricing](https://developers.cloudflare.com/r2/pricing/) rather than assuming a free allowance. Private filesystem storage needs no external account/key and remains the fallback. The API's authenticated storage boundary serves media; never publish raw candidate objects by default.

`CREATORPROOF_CANDIDATE_RETENTION_SECONDS=0` deletes candidate media after completion while retaining hashes and permitted normalized evidence. Later reinspection/side-by-side media access returns unavailable when the object is gone. To retain candidate media for a reviewed interval, configure a deliberate positive retention value and use the deletion/recovery mechanisms described in the security/operations documentation.

## 6. Optional image-source connectors

Unsplash and Pixabay search are additional source coverage, not global reverse-image search. Existing local user scanning does not depend on them.

| Connector | Variable | Setup | Fallback |
| --- | --- | --- | --- |
| Unsplash | `CREATORPROOF_UNSPLASH_ACCESS_KEY` | [Register an application](https://unsplash.com/developers), [API contract](https://unsplash.com/documentation) | Only Unsplash search unavailable |
| Pixabay | `CREATORPROOF_PIXABAY_API_KEY` | [API documentation and key dashboard](https://pixabay.com/api/docs/) | Only Pixabay search unavailable |

For Unsplash, create a developer account, open its applications page, and choose New Application. Use the application's Access Key for public image search; CreatorProof does not need its Secret Key, OAuth login, or user/account-write scopes. The public API does not document a per-search-only scope for that Access Key. Its [official API documentation](https://unsplash.com/documentation) describes app registration and public `Client-ID` authorization. The [Demo mode](https://help.unsplash.com/en/articles/3887917-when-should-i-apply-for-a-higher-rate-limit) is free under its terms with 50 requests/hour; greater/public deployment access requires approval and account-specific terms. Do not assume unlimited free production use. A specific self-service key regeneration/revocation workflow was not verified in public docs: confirm with the application page/API team, obtain an approved replacement key, and request revocation of the previous one. Do not create extra applications to evade limits.

For Pixabay, create/sign in to an account and open [API documentation](https://pixabay.com/api/docs/); the required key appears in Search Images → Parameters → `key` when authenticated. Public image search requires that key, with no account-write/OAuth permission needed; configurable per-key endpoint/read-only scopes are not documented. The API is offered free under its terms with published limits; account-approved higher limits or full image access are separate from baseline search. Its docs require 24-hour response caching and prohibit mass automated downloads. Specific self-service key regeneration/revocation controls were not verified: use the authenticated key page/provider support to obtain a replacement and confirm old-key revocation. Removing a key from CreatorProof only disables this connector locally.

Preserve provider attribution, download/reporting, caching, and hotlinking requirements in the [existing connector documentation](MARKETPLACE_CONNECTORS.md). Never claim that discovering a matching public asset proves unauthorized use or a person's country. Source location/jurisdiction facts require an attributable source and human review.
