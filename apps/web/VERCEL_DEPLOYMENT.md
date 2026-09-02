# Vercel deployment

The Git repository can be imported at its root. `vercel.json` installs and
builds `creatorproof/apps/web`, then copies the Next.js output to the repo
root so Vercel can host it. You can also set **Root Directory** to
`creatorproof/apps/web` and **Framework Preset** to Next.js. Function
handlers are capped at 60 seconds on Vercel Hobby.

## Required Vercel environment variables

Set these for Production and Preview:

```text
CREATORPROOF_API_URL=https://<render-service>.onrender.com
CREATORPROOF_API_KEY=<same scoped API credential configured on Render>
CREATORPROOF_DIRECT_UPLOAD_ENABLED=true
CREATORPROOF_BACKEND_COLD_START_BUDGET_MS=55000
CREATORPROOF_WEB_AUTH_MODE=basic
CREATORPROOF_WEB_BASIC_AUTH_USER=<demo user>
CREATORPROOF_WEB_BASIC_AUTH_PASSWORD=<random 16+ character password>
```

The API key is server-only. Never create a `NEXT_PUBLIC_` version of it. The
browser asks `/api/uploads` for a short-lived grant, PUTs the image directly to
the returned HTTPS URL, and sends only the signed `upload_token` through Vercel.
The object-store CORS policy must allow `PUT` from the final Vercel domain and
must allow every `x-amz-meta-*` header returned by the grant endpoint.

Set the build-time public proof pins
`NEXT_PUBLIC_CREATORPROOF_ISSUER_KEY_FINGERPRINT_SHA256` and
`NEXT_PUBLIC_CREATORPROOF_ISSUER`. The optional deployment fingerprint is
required only when a separately published chain deployment is enabled; leave it
unset for this off-chain Render profile. `OPENROUTER_API_KEY`, model, and site
URL are optional and affect only the evidence-explanation button.

## Deliberate limits

- Images are limited to 4,000,000 bytes and 6 megapixels so the 512 MB Render
  service has headroom while decoding. PNG, JPEG, and WebP are accepted.
- Multipart fallback exists for local development, stays below Vercel's 4.5 MB
  payload cap, and is not the production upload path.
- A sleeping Render service is retried for up to 55 seconds on Vercel Hobby. A judge can see a
  short first-request delay after inactivity, but should not receive the former
  8- or 30-second gateway timeout.
- The web rate limiter is per warm Vercel instance because free serverless
  instances share no durable state. Render's tenant quota is the authoritative
  abuse/cost control. Use a shared rate-limit store for a public production app.
- Basic Auth protects the private demo and its server-side API-key proxy. Set
  `CREATORPROOF_WEB_AUTH_MODE=public` only as a conscious opt-out.

After the Render health endpoint is green, deploy and verify:

```bash
npm ci
npm run typecheck
npm test
npm run build
```
