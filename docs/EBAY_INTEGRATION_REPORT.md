# eBay integration — 9 October 2026

## Delivered behavior

- The supplied sandbox keyset is configured only in the ignored `apps/api/.env`.
  App ID and Cert ID authorize Browse OAuth; Dev ID is retained for legacy APIs.
- The backend mints application tokens, shares them across concurrent searches,
  renews before expiry, and retries a rejected token once. Tokens are memory-only.
- eBay keyword search uses the selected marketplace, bounded pagination, a
  60-second cache and normalized listing metadata. Images download server-side
  through fixed CDN allowlists with response size and timeout limits.
- Sandbox legacy image URLs are upgraded to HTTPS only for exact sandbox CDN
  hosts. Other insecure, unexpected or credential-bearing URLs are rejected.
- The User portal offers **eBay · Sandbox**, previews listing photos, identifies
  sellers and starts the normal catalog scan from a retained source observation.
- The Admin portal offers the same selector and environment explanation. It waits
  60 seconds before the first check and continues checking after each completed
  request until paused. The previous timer stopped after its second check; that
  behavior is corrected.
- Existing history persists. Duplicate provider/environment/marketplace/item
  identities are excluded from new discoveries and keep their original scan.
- Matched listing scans use the existing copied-image classification and operator
  review/notice workspace. Item location is displayed as context and never used
  as verified seller residence or an automatic jurisdiction selection.
- `/v1/marketplaces/providers`, proxied at `/api/marketplaces/providers`, provides
  safe configuration status without returning any credentials or minting tokens.
- `.env.example`, Compose configuration, README and operational documentation
  include the new server-side settings.
- The model bundle's source revision was refreshed for the new API code. Model
  artifact hashes and qualification states were preserved.

## Verification

**Real eBay sandbox:** OAuth returned HTTP 200, Browse returned HTTP 200, the
implemented connector normalized three photo-bearing listings for `print`, and
a bounded HTTPS listing-photo download succeeded (5,426 bytes). The running
frontend gateway returned those same three listings, and the User page rendered
three result cards. Sandbox listings without photos were observed and are omitted.

**Controlled integration:** A procedural registered artwork was returned as an
eBay listing photo by an isolated provider fixture. The real API scan detected
`MATCH_FOUND`; Admin retained it as `COPIED`. Three timed checks produced one saved
record, with later checks reporting a duplicate, and pausing stopped requests.
This fixture proves the application wiring; it is separate from live sandbox data.

| Check | Result |
| --- | --- |
| Focused backend connector, monitor, health, model bundle and Phase 1 regressions | 93 passed |
| Frontend unit/contract tests | 62 passed |
| Browser integration checks against isolated API | 7 passed |
| Live User/Admin browser checks | Passed |
| Desktop control alignment and mobile overflow | Passed |
| TypeScript check and production build | Passed |
| Ruff checks on changed Python implementation/tests and fixture | Passed |
| Supplied credentials in tracked/nonignored repository files | None found |

Browser test infrastructure: `apps/web/scripts/ebay-fixture-api.py` and
`apps/web/scripts/ebay-browser-smoke.mjs`. The fixture reuses the isolated Phase 1
API and never contacts real eBay. Test servers were stopped after validation;
the user's existing API and frontend remain running.

## Start testing

1. Register a reference in the Artist portal and note its catalog ID.
2. Open `/user`, select **eBay · Sandbox**, enter that catalog and search `print`.
3. Select **Scan this image**, then inspect the stored scan evidence.
4. In `/admin`, choose the same source and catalog and press **Start monitor**.
   Wait one minute for the first check; review the new discoveries and history.

Unrelated sandbox listing photos should not match your registered artwork. For a
controlled provider-backed match, publish your reference image in a sandbox test
listing. Production monitoring requires a separate production keyset and the
appropriate Browse access; these supplied keys are sandbox credentials.

See [connector setup and API examples](MARKETPLACE_CONNECTORS.md),
[eBay OAuth credentials](https://developer.ebay.com/api-docs/static/oauth-credentials.html)
and [Browse API documentation](https://www.developer.ebay.com/api-docs/buy/static/api-browse.html).

## Screenshots

- [Live User search, desktop](assets/ebay-integration/ebay-user-live-desktop.png)
- [Live User search, mobile](assets/ebay-integration/ebay-user-live-mobile.png)
- [Admin source controls, desktop](assets/ebay-integration/ebay-admin-desktop.png)
- [Admin source controls, mobile](assets/ebay-integration/ebay-admin-mobile.png)
