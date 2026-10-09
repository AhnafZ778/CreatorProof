# CreatorProof frontend integration

Implemented on 2026-10-09, following the user's explicit request to expose the
Phase 1 backend capabilities in the frontend. This is a subsequent phase: the
original backend-only frontend freeze is superseded for this work, and its
baseline and verification artifacts remain unchanged.

## What is available

| Page | Implemented experience |
|---|---|
| `/artist` | Server-backed artwork library with thumbnails and a workspace for each work. Four tabs: Rights Passport, Creation history, Provenance, Share & export. |
| Rights Passport | All eleven permissions with six values, explanatory groups, optional presets, attribution and licensing conditions, country/platform/model/channel/audience/transformation scope, effective dates, consent source/time, policy withdrawal and explicit reissue. Saving appends a real version; history and policy hashes are readable. |
| Creation history | Append fourteen supported kinds of creation events with human/AI/system actors, contribution classification, software/model, human decisions, dates, optional asset IDs, before/after hashes and private record references. Read the timeline, verify the actual hash chain, and export the ledger. |
| Provenance | Read saved work or scan inspections and explicitly reinspect retained media. Separate manifest presence, validity, signature, signer trust, actions, models, metadata and ingredients. Explain unavailable tools and expired candidate media. |
| Share & export | Issue scoped links with a selected expiry, open/copy them, and revoke links issued in this browser even after a reload. Download the full Rights Passport, AI preferences, ai.txt fragment, TDM policy and readable rights statement from the backend. |
| `/user` | Optional intended-use territory, channel, audience, transformation, platform, model and requested permission. A completed scan shows the eight-lane Evidence Matrix, existing visual microscope/proof tools, persisted provenance and public verification controls. Notice country is separate from intended-use territory. |
| `/admin` | Stored user detections and existing monitor, review and notice workflows. Selected scans also expose the matrix, append-only matrix corrections, and an investigation workspace. Generate explicitly, inspect missing facts/evidence/next steps, and record accepted, edited or rejected output. Original output and generation receipts remain preserved. Previously generated runs can be reopened by ID; the latest run ID for each selected scan is remembered in this browser. |
| `/verify/{token}` | Anonymous, scoped public verification page with safe registration/provenance/rights summaries and packet hashes when disclosed. Clear unavailable, expired and revoked states; public JSON download. Private contact details and uploaded media are excluded. |
| `/pipeline` | Blue node-based walkthrough with eleven selectable nodes, animated connections, play/pause/reset, and three examples: licensed reuse, reuse with missing permission, and resemblance without validated copying. Explanations distinguish detection, permissions, evidence, human review and verification. Accessible from portal navigation. |

The shared styling uses the existing Geist fonts, black/glass surfaces, rounded
panels, portal accents and semantic evidence colors. The layout adapts at desktop,
tablet and phone widths. Artwork tabs support arrow/Home/End keyboard navigation;
controls have focus states and status announcements. Pipeline animation respects
reduced-motion preferences.

## Live behavior and simulation boundaries

Artist saves, ledger verification, provenance inspection, exports, matrix reads,
matrix corrections, investigation generation/review and public-token operations
call the real backend through finite Next route handlers. They are not local UI
mock data. The artist library reloads from the server; browser storage is a cache.

The pipeline is explicitly labeled **Illustrative walkthrough**. Playing it does
not run detection, use artist data, call an AI provider or create/send notices.
Real results appear in the User and Admin workspaces.

Investigation generation uses the configured backend provider only when requested.
Provider failures are displayed and their persisted failed-run receipt remains
readable. Human edits are separate from immutable generated content. The existing
notice workspace and its human-controlled delivery flow remain in place.

The frontend cannot add unavailable backend capabilities: signed C2PA authoring,
proof of ownership, a legal infringement finding, country-of-residence discovery,
and blanket scanning of the internet are not produced by these controls.

Candidate retention remains governed by backend `CANDIDATE_RETENTION_SECONDS`.
Its default of zero removes candidate media after completion. Stored evidence is
still readable, but later visual comparison and reinspection need retained media.
Admin shows an explanatory placeholder if the candidate is gone. To retain media
for an authorized review period, configure a positive TTL on the backend before
new scans; changing it does not recover already removed files.

## Gateway and disclosure boundaries

The gateway exposes only an explicit list of Phase 1 routes and HTTP methods.
Writes use the existing same-origin and rate-limit guard, bounded JSON, readiness
checks and non-replayed mutations. Credentials remain server-side. Backend
redirects are refused on the new routes and configured gateway deadlines apply.

Basic web authentication, when configured, protects Artist, User, Admin and
private API routes. Only the exact 64-character public-token verification API
path bypasses that login. Public routes use `no-store`, `no-referrer` and
`noindex, nofollow`. Public fetches do not attach the backend API key.

Raw verification tokens and active URLs stay in component memory. Browser history
for revocation stores only token record IDs, expiry, scopes and revoked state.
Full authenticated exports can include licensing contact information, which the
export panel explains separately from public disclosure.

## Validation

| Check | Result |
|---|---|
| Frontend unit/contract checks | 60 passed |
| TypeScript | `npm run typecheck` passed |
| Production build | `npm run build` passed, including standalone assets |
| Focused backend regressions | 126 passed: passports, evidence/provenance, investigations, declared context/retention and historical frontend audit integrity |
| Real API + Chromium browser smoke | 15 groups passed; no browser runtime errors |
| Responsive checks | Artist, User, Admin and Pipeline at 1440, 768 and 375 px without document overflow |

Browser tests used a separate SQLite database and procedural artwork, with real
registration, policy versioning, exports, ledger persistence, exact-copy scans,
matrix persistence/correction, public disclosure/revocation and human reviews.
The assistant output was deliberately supplied by a labeled controlled fixture;
unavailability was also tested. These checks validate integration and state
handling, not the quality or availability of live AI providers. No paid API
calls, real notices or production artwork changes were needed.

The smoke checks cover default zero-TTL candidate deletion, retained provenance,
scan-time rights snapshots, private-contact exclusion, anonymous public access,
authentication/CSRF boundaries, preserved original assistant output, review
reloads, failed-run persistence and interactive pipeline playback.

Screenshots and browser results are under
`docs/assets/frontend-integration/`; artwork and assistant output in them are
explicit test fixtures. The expired/revoked fixture links are not real artist links.

Review the [Rights Passport](assets/frontend-integration/artist-passport.png),
[creation history](assets/frontend-integration/artist-history.png),
[Evidence Matrix](assets/frontend-integration/user-evidence.png),
[reviewed investigation](assets/frontend-integration/admin-investigation.png),
[node walkthrough](assets/frontend-integration/pipeline-1440.png), and
[phone controls](assets/frontend-integration/permissions-phone.png).

## Repeat the browser check

From `apps/api`, use the project's Python environment:

```bash
FRONTEND_FIXTURE_DIR=/tmp/creatorproof-frontend-validation \
  .venv/bin/python ../web/scripts/phase1-fixture-api.py
```

In another terminal, from `apps/web`:

```bash
CREATORPROOF_WEB_DIST_DIR=.next-frontend-validation \
CREATORPROOF_API_URL=http://127.0.0.1:8011 \
CREATORPROOF_API_KEY=frontend-integration-fixture-key \
CREATORPROOF_WEB_AUTH_MODE=basic \
CREATORPROOF_WEB_BASIC_AUTH_USER=fixture \
CREATORPROOF_WEB_BASIC_AUTH_PASSWORD=frontend-fixture-password \
  npm run dev -- --port 3011
```

Then, with Playwright and its Chromium installed, run from `apps/web`:

```bash
FRONTEND_FIXTURE_DIR=/tmp/creatorproof-frontend-validation \
  node scripts/phase1-browser-smoke.mjs
```

If Playwright is installed outside this package, set
`PLAYWRIGHT_MODULE_PATH` to its module entry point. An existing Chromium binary
can be selected with `PLAYWRIGHT_CHROMIUM_PATH`. The fixture uses no project
`.env` configuration and should only run against a disposable local directory.

The optional output directory isolates the validation server from an existing
development server. Next may regenerate `next-env.d.ts` and add its output types
to `tsconfig.json`; remove validation-only references after stopping the fixture,
or restart the normal development server to regenerate its own type references.
