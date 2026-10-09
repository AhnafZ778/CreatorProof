# Image-source connectors

CreatorProof has server-side connectors for Unsplash, Pixabay and eBay. They are
discovery sources for testing and monitoring: the provider result is recorded as
a short-lived observation, the image is downloaded server-side, and the existing
CreatorProof scan pipeline performs the comparison against a registered catalog.

## Configure the API

Add these values to `apps/api/.env` (or the deployment secret store):

```dotenv
CREATORPROOF_UNSPLASH_ACCESS_KEY=your-unsplash-access-key
CREATORPROOF_PIXABAY_API_KEY=your-pixabay-api-key
CREATORPROOF_EBAY_CLIENT_ID=your-app-id
CREATORPROOF_EBAY_CLIENT_SECRET=your-cert-id
CREATORPROOF_EBAY_DEV_ID=your-dev-id
CREATORPROOF_EBAY_ENVIRONMENT=sandbox
CREATORPROOF_EBAY_MARKETPLACE_ID=EBAY_US
```

The web app never receives provider credentials or OAuth tokens. Do not put them in
`apps/web/.env.local` or client-side JavaScript.

## Search

The backend requires an API credential with the existing `X-API-Key` header:

```bash
curl -sS http://localhost:8000/v1/marketplaces/search \
  -H 'X-API-Key: change-me-before-sharing' \
  -H 'Content-Type: application/json' \
  -d '{"provider":"pixabay","query":"painting","per_page":3}'
```

Use `"provider":"unsplash"` for Unsplash. The response contains normalized
metadata and an `observation_id` for each result. Observations are stored for 24
hours so the scan step can use the exact result that was reviewed.

The Next.js proxy exposes the same operation at `/api/marketplaces/search`.

For eBay use `{"provider":"ebay","query":"print","per_page":9}`. The supplied
keyset is configured in the ignored API `.env` as **sandbox**. Authentication and
Browse discovery were verified against eBay; a `print` search returned three usable
listing photos. Sandbox inventory varies and many listings have no images. Such
listings are omitted from image scanning. Legacy HTTP image URLs on the exact
sandbox CDN hosts are upgraded to HTTPS; no insecure download fallback is used.

`GET /v1/marketplaces/providers` (through `/api/marketplaces/providers`) reports
credential presence, environment and marketplace only. It does not authenticate
with providers and never reports presence as successful live access.

## Test through the frontend

1. Register an artist's reference in `/artist` and note its catalog ID.
2. Open `/user`, choose **eBay · Sandbox**, set that catalog ID, and search `print`.
3. Choose **Scan this image** to compare a listing photo with the registered works.
4. Open `/admin`, choose **eBay · Sandbox** and the same catalog, then **Start monitor**.
   The first check starts after 60 seconds. Checks repeat 60 seconds after each
   previous request completes while the page is open, until paused.
5. Review saved discoveries, copied-image findings, source evidence and notice drafts.
   Matching is evidence for review; unrelated sandbox listings will usually not match
   your artwork. For a controlled real-provider match, publish a sandbox test listing
   using the registered artwork through eBay's sandbox tools.

The API owns the credentials, token renewal, bounded downloads and deduplication.
eBay asset IDs include environment and marketplace so sandbox fixtures cannot
collide with production listings in saved history. Search responses cache for
60 seconds; access tokens stay in process memory until shortly before expiry.

To search real listings, obtain the **production** keyset and applicable Browse API
access in the [eBay Developer account](https://developer.ebay.com/my/keys), replace
the Client ID/Secret, set `CREATORPROOF_EBAY_ENVIRONMENT=production`, and restart the
API (and worker if used). A sandbox token cannot authorize production calls.
For Docker Compose, supply these values in the root `.env` or deployment environment;
the container does not automatically read `apps/api/.env` on the host.

## Scan a selected result

Pass the observation ID returned by search:

```bash
curl -sS -X POST http://localhost:8000/v1/marketplaces/scan \
  -H 'X-API-Key: change-me-before-sharing' \
  -H 'Content-Type: application/json' \
  -d '{
    "observation_id":"obs_REPLACE_WITH_THE_ID_FROM_SEARCH",
    "catalog_id":"default",
    "intended_use":"marketplace-monitoring"
  }'
```

The scan response contains the normal CreatorProof scan ID and the selected
source metadata. Once the scan completes, the evidence packet includes the same
`source_observation` block, including the provider, source page, image URL,
creator, and observation timestamp.

The Next.js proxy exposes the scan at `/api/marketplaces/scan`.

## Provider requirements

- [Unsplash developer documentation](https://unsplash.com/documentation): search
  starts in demo mode and the API expects an `Authorization: Client-ID ...`
  header. CreatorProof uses the returned CDN URL and triggers Unsplash's
  `download_location` event when a result is selected for scanning.
- [Pixabay API documentation](https://pixabay.com/api/docs/): the API key is sent
  server-side, and the search response is cached for 24 hours as required by
  Pixabay's usage limits.
- [eBay OAuth credentials](https://developer.ebay.com/api-docs/static/oauth-credentials.html)
  and [authorization](https://developer.ebay.com/develop/guides/sell/authorization):
  App ID is the Client ID and Cert ID is the Client Secret. Browse uses a
  client-credentials application token; the legacy Dev ID is stored but not needed
  for this flow. Sandbox and production credentials and hosts are separate.
- [eBay Browse API](https://www.developer.ebay.com/api-docs/buy/static/api-browse.html):
  keyword discovery uses `item_summary/search`, pagination and the configured
  marketplace header. This connector searches the selected keywords and pages;
  it does not crawl all eBay listings or implement eBay reverse-image search.

The listing seller is labeled **Seller**, rather than assumed to be the artist.
The item's location is retained as metadata and is not treated as verified seller
residence or grounds for selecting a notice jurisdiction. Operators still review
and choose the jurisdiction before sending a notice.

## Local verification

Run the connector tests:

```bash
cd apps/api
uv run --no-sync python -m pytest -q tests/test_marketplaces.py tests/test_ebay_marketplace.py tests/test_admin_monitor.py
```

The test suite covers provider response normalization, observation persistence,
bounded image downloads, cache-key redaction, and fail-closed behavior when a key
is missing.
