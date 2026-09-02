# Deploy CreatorProof on Vercel + Render

This profile is suitable for a low-traffic demonstration: Next.js runs on
Vercel and one lean API process runs on Render. PostgreSQL, private object
storage and remote SSCD/CSD inference are mandatory. The Render container does
not load PyTorch models or blockchain libraries.

It is not a zero-dependency deployment. A scan needs Render, PostgreSQL, the
private bucket, the two remote embedding lanes and Sightengine. Validate all of
them before a judged demo.

## Architecture and hard limits

| Component | Deployment | Responsibility |
| --- | --- | --- |
| Web | Vercel, root `creatorproof/apps/web` | UI, authenticated API proxy, direct-upload grant flow |
| API | Render Blueprint `creatorproof/render.yaml` | Validation, orchestration, geometry, policy and evidence packets |
| Database | Render Postgres | Tenant data, RLS and recoverable job state |
| Media | Private AWS S3, Cloudflare R2 or compatible storage | Uploads and derived evidence; never Render's filesystem |
| Copy/style models | External HTTPS inference service | Pinned 512-dimensional SSCD and 768-dimensional CSD embeddings |
| AI-origin model | Sightengine | Original-media `genai` request only; no local fallback |

The production contract limits an image to 4,000,000 bytes and 6,000,000
decoded pixels. Direct browser-to-bucket PUTs avoid Vercel's 4.5 MB Function
request/response limit. The API validates the stored object's size, type,
metadata and decoded pixels before accepting it.

## 1. Prepare dependencies

Create these before deploying either application:

1. A private S3-compatible bucket with public access disabled. Its credentials
   need object read, write, list and delete access only to this bucket.
2. HTTPS endpoints implementing the remote inference contract below. They may
   be two endpoints or one service that handles both lanes.
3. Sightengine API credentials with enough `genai` quota for registration and
   scan rehearsals.
4. A Git commit containing the deployment changes. Never commit generated
   secrets, a database file or a real `.env` file.

Apply [`s3-cors.example.json`](s3-cors.example.json) to the bucket after
replacing the origin with the exact production Vercel domain. Add an exact
preview domain separately only when preview uploads are required. Do not use a
broad `*` origin. The browser must be allowed to send `Content-Type` and every
signed `x-amz-meta-*` header; it must not add headers not returned in the upload
grant.

Configure a bucket lifecycle rule that deletes objects under `incoming/` after
one day. The application removes successfully consumed uploads immediately;
the lifecycle rule cleans uploads abandoned before completion. Configure any
longer reference/candidate retention rules separately; never apply the one-day
rule to `references/`.

For Cloudflare R2, use region `auto` and the account's HTTPS S3 endpoint. For
AWS S3, use the real AWS region and leave `CREATORPROOF_S3_ENDPOINT_URL` empty.

## 2. Generate correlated secrets

Run this locally from `creatorproof/apps/api` in an environment where the API
dependencies are installed:

```bash
uv run python -m scripts.generate_deployment_secrets
```

Copy only the cross-provider values named below into the matching Render and
Vercel fields. The helper also prints standalone pepper, database-password and
upload-token values for deployments that do not use the Blueprint; this
Blueprint generates those three values itself. Do not redirect the output into
the repository, paste it into logs, or store it in a deployment note.

These values are correlated:

- Render `CREATORPROOF_BOOTSTRAP_API_KEY` and Vercel
  `CREATORPROOF_API_KEY` must be the same `cpk_...` value.
- Render `CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX` must match Render
  `CREATORPROOF_TRUSTED_ISSUER_KEY_SHA256` and Vercel
  `NEXT_PUBLIC_CREATORPROOF_ISSUER_KEY_FINGERPRINT_SHA256`.

Render may generate the runtime database password, pepper, unused development
key and upload-token secret because no other service needs their plaintext.
Rotate the bootstrap/API key through the credential API after the demo if it
has been shared with another operator.

## 3. Deploy Render

Create a Render Blueprint from the repository and set its Blueprint path to
`creatorproof/render.yaml`. Its `rootDir` is `creatorproof/apps/api`, resolved
from this repository's root. Render also resolves `dockerContext` and
`dockerfilePath` from the repository root, so the Blueprint explicitly points
both at `creatorproof/apps/api`. It creates exactly one free Docker web service
and one free PostgreSQL database.

Supply every value marked `sync: false`:

- S3/R2 bucket, region, optional endpoint, access key and secret;
- the generated bootstrap key, signing seed and signing fingerprint;
- SSCD URL/token and CSD URL/token; and
- Sightengine API user/secret.

Do not add `CREATORPROOF_DATABASE_URL` manually. On every boot,
`python -m scripts.render_start` takes a PostgreSQL advisory lock, provisions or
updates the `creatorproof_app` login without superuser or `BYPASSRLS`, runs
Alembic with the database-owner URL, refreshes table/sequence grants, removes
the owner credentials from the process environment, and launches one Uvicorn
worker with the restricted runtime URL. Concurrent deploys therefore cannot run
the migration section simultaneously.

The API's first successful startup stores the bootstrap credential as a digest,
not plaintext. Reusing the same configured key is idempotent. Startup refuses a
different bootstrap key once credentials exist so an environment edit cannot
silently replace the administrator.

Wait for both endpoints to return HTTP 200:

```bash
curl --fail-with-body https://YOUR-API.onrender.com/healthz
curl --fail-with-body https://YOUR-API.onrender.com/readyz
```

`/readyz` covers the database and queue. Learned-model providers are deliberately
reported as capabilities rather than readiness blockers, so the full scan smoke
test below is still required.

## 4. Deploy Vercel

Import the same repository in Vercel. The repo-root `vercel.json` builds
`creatorproof/apps/web`; you can also set **Root Directory** to that folder
and **Framework Preset** to Next.js.

Set these for Production and, if used, Preview:

```text
CREATORPROOF_API_URL=https://YOUR-API.onrender.com
CREATORPROOF_API_KEY=<the Render bootstrap cpk_... key>
CREATORPROOF_DIRECT_UPLOAD_ENABLED=true
CREATORPROOF_BACKEND_COLD_START_BUDGET_MS=55000
CREATORPROOF_WEB_AUTH_MODE=basic
CREATORPROOF_WEB_BASIC_AUTH_USER=<private demo username>
CREATORPROOF_WEB_BASIC_AUTH_PASSWORD=<random value, at least 16 characters>
NEXT_PUBLIC_CREATORPROOF_ISSUER_KEY_FINGERPRINT_SHA256=<generated public fingerprint>
NEXT_PUBLIC_CREATORPROOF_ISSUER=creatorproof
```

`CREATORPROOF_API_KEY` is server-only. Never create a `NEXT_PUBLIC_` copy.
`CREATORPROOF_WEB_AUTH_MODE=public` is a conscious opt-out and should only be
used when another access boundary protects the site. `OPENROUTER_API_KEY`,
`OPENROUTER_MODEL` and `OPENROUTER_SITE_URL` are optional and affect only the
evidence-explanation feature.

Deploy only after the Render service is healthy. Then open the production URL,
authenticate, register a known work, scan a related image and an unrelated
image, wait for both jobs to finish, and download/verify an evidence packet.

## Remote inference contract

Both configured endpoints receive `POST` with `Authorization: Bearer <token>`,
`X-CreatorProof-Embedding-Contract:
creatorproof.embedding-inference.request.v1`, `Accept: application/json`, and a
JSON body with no extra fields:

```json
{
  "schema_version": "creatorproof.embedding-inference.request.v1",
  "request_id": "opaque-request-id",
  "lane": "COPY",
  "model_identity": "SSCD_DISC_MIXUP_TORCHSCRIPT_LOCAL_ARTIFACT",
  "preprocessing_identity": "SSCD_RGB_SHORTEST_SIDE_288_IMAGENET_NORMALIZATION_V1",
  "dimensions": 512,
  "required_normalization": "L2_UNIT_V1",
  "images": [
    {
      "id": "0",
      "media_type": "image/png",
      "width": 1024,
      "height": 768,
      "sha256": "<sha256-of-decoded-image-reencoded-as-this-PNG>",
      "data_base64": "<lossless-RGB-PNG-base64>"
    }
  ]
}
```

The style lane changes these fields:

```text
lane=STYLE
model_identity=CSD_VIT_L_EXTERNAL_CHECKPOINT
preprocessing_identity=UPSTREAM_CSD_TRANSFORMS_BRANCH0
dimensions=768
```

Return status 200 and `Content-Type: application/json` with no extra fields:

```json
{
  "schema_version": "creatorproof.embedding-inference.response.v1",
  "request_id": "<same request id>",
  "lane": "COPY",
  "model_identity": "SSCD_DISC_MIXUP_TORCHSCRIPT_LOCAL_ARTIFACT",
  "preprocessing_identity": "SSCD_RGB_SHORTEST_SIDE_288_IMAGENET_NORMALIZATION_V1",
  "model_artifact_sha256": "9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56",
  "dimensions": 512,
  "normalization": "L2_UNIT_V1",
  "embeddings": [
    {
      "id": "0",
      "source_sha256": "<same image sha256>",
      "vector": [0.0]
    }
  ]
}
```

The example vector is abbreviated; it must contain exactly 512 finite values
for COPY or 768 for STYLE and its L2 norm must be within 0.005 of 1.0. The STYLE
artifact hash is
`40e92fad63a361b8136100cd234c42d401ef9b34ff1748234318929ebcc7e7a1`.
CreatorProof also rejects changed request IDs, lanes, identities, source hashes,
artifact hashes, result IDs, redirects and non-JSON responses. Retryable status
codes are 408, 429, 500, 502, 503 and 504.

## Smoke test and monitoring

Before the judged session:

1. Wake Render with `/readyz` at least two minutes early.
2. Complete one browser direct upload and confirm the bucket has no public URL.
3. Register at least two creators with enough works for the intended style test.
4. Run one copy-positive, one unrelated, one AI-generated and one human-created
   image through the production UI.
5. Confirm Render logs contain no owner URL, API key, S3 secret or remote token.
6. Confirm the usage view has enough Sightengine quota for the session.

Use Render logs and `/readyz` for service health, and use the UI result's
capability/evidence status for remote-model failures. A Sightengine outage is
reported as unavailable in `sightengine_only` mode; it never loads a local model
or fabricates a human-origin result.

## Free-tier boundaries

Render's free web service has 512 MB RAM and 0.1 CPU, spins down after 15 minutes
without inbound traffic, and can take about a minute to wake. Its filesystem is
ephemeral. A free Render Postgres database expires after 30 days, and free web
services cannot use a paid pre-deploy command or a separate free background
worker. The Blueprint is therefore a demonstration profile, not a guarantee of
latency, uptime or durable long-term storage.

The single local worker prevents parallel scans from exhausting memory, but a
queue can grow and geometry remains CPU-bound. For a public or persistent
deployment, upgrade the web service, use non-expiring PostgreSQL, and move jobs
to a durable Redis-backed worker. S3/R2, inference-provider and Sightengine
quotas/costs are independent of Render's free allowance.

Current platform references:

- [Render free services](https://render.com/docs/free)
- [Render compute plans](https://render.com/docs/compute-plans)
- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
- [Render deploy behavior](https://render.com/docs/deploys)
- [Vercel Function limits](https://vercel.com/docs/functions/limitations)

## Rollback

Keep the last known-good Git commit and test migrations against a disposable
database before merging. If a web release fails, promote the prior Vercel
deployment. If an API release fails before a schema change, redeploy the prior
Git commit from Render. Do not run an automatic Alembic downgrade against live
data.

For a migration that changes or removes data, first take an external PostgreSQL
backup and document a tested restore procedure. If that migration has already
committed, restore the compatible database backup into a new database, point a
fresh service at it, validate `/readyz` and a complete scan, then switch traffic.
Object-store objects should remain backward compatible and private throughout
the rollback.
