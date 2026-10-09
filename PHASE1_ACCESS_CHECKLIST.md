# CreatorProof Phase 1 Access Checklist

| Variable | Required? | Purpose | Provider | Setup URL | Fallback |
| --- | --- | --- | --- | --- | --- |
| `CREATORPROOF_DATABASE_URL` | Yes, local default supplied | Evidence and rights persistence | SQLite/PostgreSQL | [PostgreSQL setup](https://www.postgresql.org/docs/current/tutorial-install.html) | SQLite for local development |
| `CREATORPROOF_JOB_BACKEND` | Yes, local default supplied | Job execution transport | Local/Redis | [Redis local install](https://redis.io/docs/latest/operate/oss_and_stack/install/install-redis/) | `local` queue |
| `CREATORPROOF_REDIS_URL` | Only if `JOB_BACKEND=redis` | Durable Redis job transport | Redis | [Redis Docker setup](https://redis.io/docs/latest/operate/oss_and_stack/install/install-stack/docker/) | Local queue; no paid Redis service required |
| `CREATORPROOF_STORAGE_PROVIDER`, `CREATORPROOF_STORAGE_ROOT` | Yes, local defaults supplied | Private media and evidence storage | Filesystem/S3 | [Backend provider guide](docs/PHASE1_PROVIDER_SETUP.md) | Private local filesystem |
| `CREATORPROOF_S3_BUCKET`, `CREATORPROOF_S3_REGION` | Only with S3 | Bucket selection | S3-compatible | [AWS bucket setup](https://docs.aws.amazon.com/AmazonS3/latest/userguide/creating-buckets-s3.html) | Local storage |
| `CREATORPROOF_S3_ENDPOINT_URL` | Only for custom endpoint | S3-compatible API address | R2/other | [R2 S3 API](https://developers.cloudflare.com/r2/api/s3/api/) | AWS default endpoint/local storage |
| `CREATORPROOF_S3_ACCESS_KEY_ID`, `CREATORPROOF_S3_SECRET_ACCESS_KEY` | Only with S3 | Private object access | S3-compatible | [AWS IAM keys](https://docs.aws.amazon.com/IAM/latest/UserGuide/access-key-self-managed.html), [R2 tokens](https://developers.cloudflare.com/r2/api/tokens/) | Local storage |
| `CREATORPROOF_SIGHTENGINE_API_USER`, `CREATORPROOF_SIGHTENGINE_API_SECRET` | Optional | Existing `genai` origin detector | Sightengine | [API credentials](https://dashboard.sightengine.com/api-credentials), [credential instructions](https://sightengine.com/faq/get-my-credentials) | Explicit vendor unavailable; local fallback only if already configured and recorded |
| `CREATORPROOF_C2PA_BINARY`, `CREATORPROOF_C2PA_EXPECTED_VERSION`, `CREATORPROOF_C2PA_EXPECTED_BINARY_SHA256` | Optional; no API key | Read-only manifest inspection | Official CAI `c2patool` | [CAI tooling](https://opensource.contentauthenticity.org/), [releases](https://github.com/contentauth/c2pa-rs/releases) | `PROVIDER_UNAVAILABLE` |
| `CREATORPROOF_AIAND_BASE_URL`, `CREATORPROOF_AIAND_API_KEY`, `CREATORPROOF_AIAND_MODEL` | Optional | Structured investigation summaries/drafts | AI & Inference | [Console](https://console.aiand.com), [key creation](https://docs.aiand.com/organizations/api-keys/) | Failed/unavailable investigation; deterministic admin template remains available |
| `CREATORPROOF_VISIBLE_AI_MARKER_BINARY` | Optional | Existing visible-label OCR lane | Local Tesseract | [Tesseract install](https://tesseract-ocr.github.io/tessdoc/Installation.html) | OCR coverage unavailable |
| `CREATORPROOF_SSCD_MODEL_PATH`, `CREATORPROOF_STYLE_CSD_MODEL_PATH`, existing bundle hashes | Required for learned lanes, optional for backend rights features | Local copy/profile retrieval | Existing model bundle | [Model setup](MODELS.md) | Conservative scope/abstention; baseline only when policy permits |
| `CREATORPROOF_UNSPLASH_ACCESS_KEY` | Optional | Unsplash source search | Unsplash | [Application registration](https://unsplash.com/developers) | Only this connector unavailable |
| `CREATORPROOF_PIXABAY_API_KEY` | Optional | Pixabay source search | Pixabay | [API/key page](https://pixabay.com/api/docs/) | Only this connector unavailable |
| `CREATORPROOF_CANDIDATE_RETENTION_SECONDS` | Explicit local default `0` | Candidate deletion/retention interval | Local policy | [Privacy boundaries](docs/PHASE1_SECURITY.md) | Zero-retention deletion; media cannot be revisited after deletion |
| `CREATORPROOF_PUBLIC_VERIFICATION_BASE_URL` | Optional; not a secret | Trusted HTTPS origin for absolute verification links | Your deployment | [Verification API](docs/AI_RIGHTS_PASSPORT.md) | Returns relative `/verify/{token}` path; never trusts request Host |

For supplied Compose only, root `.env` also accepts `CREATORPROOF_POSTGRES_OWNER_PASSWORD`, `CREATORPROOF_POSTGRES_RUNTIME_PASSWORD`, `CREATORPROOF_MIGRATION_DATABASE_URL`, and `CREATORPROOF_RUNTIME_DATABASE_URL`. These configure bootstrap/role connections; they are not backend Settings names. Database/Redis URLs containing passwords are secrets. Do not reuse the development passwords in a hosted deployment.

## Accounts, permissions, costs, and credential lifecycle

Public documentation was checked on 2026-10-09; account entitlements and live acceptance remain unverified. Exact setup and lifecycle details are in the [provider guide](docs/PHASE1_PROVIDER_SETUP.md). Read-only inspection/search does not imply that all providers support configurable read-only keys.

| Capability | Account/credential and minimum access | Cost and rotation/revocation |
| --- | --- | --- |
| Sightengine | Dedicated account's API ID/secret for image analysis; configurable per-key/model restrictions are not publicly established. | [Free testing/paid plans](https://sightengine.com/pricing); verify the account's model allowance/quota. Replacement/revocation UI is unverified: confirm with its credentials page/support. |
| AI & Inference | Organization inference key from console Settings → API Keys → Create; member can manage own keys. No management JWT/admin role is needed at runtime; per-model key scopes are not documented. | [Prepaid token billing](https://docs.aiand.com/models/pricing/), account-specific rates/credit. Create/deploy replacement, then [revoke old key](https://docs.aiand.com/organizations/api-keys/); member removal alone does not revoke keys. |
| Unsplash | Developer application Access Key for public search; no Secret Key, OAuth, or user-write scopes. Search-only key restrictions are not documented. | [Free Demo quota](https://help.unsplash.com/en/articles/3887917-when-should-i-apply-for-a-higher-rate-limit); production approval/terms vary. Confirm replacement and old-key revocation with the application page/API team; exact controls unverified. |
| Pixabay | Logged-in [API docs/key page](https://pixabay.com/api/docs/); public image search key, with no documented configurable endpoint scopes. | Free API under published limits/terms; higher access is account-specific. Confirm replacement/revocation with key page/support; exact controls unverified. |
| S3 / R2 | AWS account with scoped IAM key, or Cloudflare account with bucket-scoped Object Read & Write token. Read/write/delete objects and needed prefix listing; no runtime bucket administration. | Usage/account-specific [S3](https://aws.amazon.com/s3/pricing/) or [R2](https://developers.cloudflare.com/r2/pricing/) charges. Replace/deploy/test, then deactivate/delete old IAM key or revoke old R2 token. Local filesystem requires no account/key. |
| PostgreSQL | Local database needs no vendor key; hosted account chosen by operator. Separate migration owner and non-owner runtime role with application read/write permissions, without superuser or `BYPASSRLS`. | Hosted costs/dashboard are provider-specific. [Rotate role password](https://www.postgresql.org/docs/17/sql-alterrole.html), update secrets and recycle connections; revoke login and explicitly close existing sessions. SQLite remains local fallback. |
| Redis | Local queue needs no account/key. Redis deployment uses dedicated ACL username/password in Redis URL, necessary queue/stream/lease reads/writes, and remote TLS; managed account optional. | Managed costs/TLS depend on plan. [ACL password/user replacement](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/), then revoke old credential; [user deletion](https://redis.io/docs/latest/commands/acl-deluser/) closes connections. `PING` does not prove queue ACLs. |

C2PA/Tesseract/local model inspection has no provider API key or paid-account requirement. Required binaries, model artifacts and hash/version checks still have to pass; no trust/calibration qualification is implied by their installation.

## Operational requirements

1. Store all credentials in the environment or a secret manager.
2. Limit credentials to the permissions above. Image search/inspection needs no publishing or administrative rights; database/storage/queue runtime access requires scoped writes. Where a vendor does not document configurable key scopes, do not claim that its key enforces them.
3. From `apps/api`, run `uv run python -m scripts.phase1_preflight` before deployment. It reports configured remote providers separately from live availability and never prints secrets.
4. Run `uv run python -m scripts.phase1_preflight --live` for read-only database/Redis connectivity checks. This does not call billable remote providers. An authorized creator-owned scan/investigation validates the actual provider contracts; inspect returned coverage/status instead of assuming credentials prove health.
5. For routine rotation, create a replacement, update backend/API and worker secrets, restart/reconnect, and validate the capability before provider-side revocation of the old credential. Revoke exposed credentials immediately. Local deletion and account-member removal are not proof of key revocation.
6. Never copy secrets into logs, fixtures, documentation, prompts, or public verification responses.

For production, preserve the existing runtime PostgreSQL RLS role, private S3 storage, authentication/signing keys, and deployment security requirements. A local prototype does not require external managed accounts. See [the complete setup guide](docs/PHASE1_PROVIDER_SETUP.md) for commands and [security boundaries](docs/PHASE1_SECURITY.md).

## Explicitly deferred

EAS/blockchain wallets and gas, email delivery, automatic notices, arbitrary remote image fetching, custom GPU infrastructure, and marketplace partner credentials are not required for Phase 1 completion.
