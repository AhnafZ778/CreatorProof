# CreatorProof v0.10.0 — model-hardened creative evidence workspace

Build signature: **MODEL-ACCURACY-HARDENING-2026.08.10**.

You can identify this build immediately: the top bar says `CreatorProof v0.10.0`. Every completed
case starts with a typed source-coverage statement and one plain-language bottom line, followed by three independent question cards:
**Was AI used?**, **Does it reuse a work?**, and **Does it resemble a creator?** Raw forensic detail
is collapsed by default.

CreatorProof is a source-scoped, pre-publication creative-rights evidence API. This repository is a working image-first prototype shaped around the final architecture whitepaper.

It deliberately does **not** claim to determine copyright infringement, originality, or ownership. It returns evidence and separate policy outcomes:

- `match_status`: `MATCH_FOUND`, `INCONCLUSIVE`, `NO_MATCH_IN_CHECKED_SOURCES`, `SCOPE_INCOMPLETE`, `ERROR`
- `policy_action`: `PASS_BY_POLICY`, `REVIEW`, `BLOCK`
- `rights_path`: `EXISTING_LICENSE`, `LICENSE_AVAILABLE`, `NO_LICENSE_INFO`, `DISPUTED`
- `anchor_status`: `NOT_REQUESTED`, `PENDING`, `ANCHORED`, `FAILED`, `REVOKED`

The v0.10.0 release retains the v0.9.2 safety invariants and adds measurable model-system
hardening:

- SSCD candidate retrieval now evaluates the whole image plus five deterministic overlapping
  regions, while final copy findings still require geometry and aligned structure.
- Aligned structural scoring is restricted to geometry-verified support regions, reducing dilution
  when a copied patch appears inside unrelated content.
- Selected creator profiles use a family-wise multiplicity correction; choosing the best profile
  from many candidates can no longer use a naive one-profile tail value.
- Benchmarks bind prediction rows, labels, thresholds, corpus manifests, bundle identity, and
  report content by digest, with source-lineage clustered uncertainty.
- Runtime telemetry, drift triggers, durable queue recovery, and identity-bound atomic embedding
  caches make failures and stale results visible.

The retained truthful-scope invariants are:

- `NO_MATCH_IN_CHECKED_SOURCES` is impossible unless the declared catalog coverage is `COMPLETE`.
- Empty, partial, degraded, truncated, or failed scope routes to `SCOPE_INCOMPLETE` and `REVIEW`.
- An idempotency key is bound to candidate bytes, catalog, and intended use; changed payloads return
  `409 IDEMPOTENCY_PAYLOAD_MISMATCH`.
- AI-origin checks run as `DISABLED`, `INFORMATIONAL`, or `REQUIRED`; the default informational lane
  cannot independently change policy.
- Only `CORROBORATED` rights claims can authorize a recorded use. Asserted, disputed, superseded,
  and revoked claims remain review-only.

## What works now

- Multi-tenant-shaped API-key boundary with a seeded development tenant.
- Independent AI-origin lane with official C2PA inspection, the official Community Forensics
  safetensors provider, an Apache-2.0 GRIP CLIP-detector adapter, delivery-transformation probes,
  multi-crop spatial consensus, held-out provider calibration, evidence-family fusion, and abstention.
- Optional Sightengine-primary routing sends the accepted original media once to the server-side
  `genai` API, preserves global and generator-category cues, and activates the local detector set
  only on an operational API failure. A valid low remote score never triggers score shopping.
- Community Forensics now uses its official evaluation transform: resize the shorter side to 440,
  then center-crop 384. The previous direct 384×384 force-fit was an input-distribution bug.
- Origin semantics stay honest: missing C2PA is unknown; one raw low model response cannot imply
  human creation; and an uncalibrated raw model output is never rendered as a percentage.
- Confident positive and quiet origin decisions require complementary evidence families. Multiple
  variants of one model family cannot masquerade as independent agreement.
- Local visible-label OCR checks the full image and overlapping corners for explicit AI-use text.
  A found label forces review and is highlighted on the image; missing text is neutral and a label
  is never treated as trusted provenance.
- The understandable score is restored as two separate 0–100 readouts: **AI signal** and **Evidence
  quality**. Both explain their inputs and are explicitly not probabilities.
- Catalog matching cannot suppress origin. Positive, uncertain, unavailable, and disabled origin
  states remain visible, while the explicit policy mode determines whether they can affect policy.
- Reference-work image registration with SHA-256/pHash fingerprints plus cached learned descriptors
  when SSCD is active.
- Exhaustive pairwise verification for declared demo catalogs up to the configured safety bound
  (64 by default); larger catalogs expose truncation and cannot produce a complete no-match.
- SSCD `sscd_disc_mixup` TorchScript descriptors (512D, cosine-ranked) when the official model and
  PyTorch runtime are installed; explicit pHash fallback otherwise.
- Independent creator-profile resemblance retrieval: versioned, consent-backed profile manifests
  define authorized anchor pools. Same-`claimant` grouping remains available only as an explicitly
  unversioned prototype and cannot escalate policy.
  v0.8 retains mean CSD cosine plus CSD+ CSLS local-density correction, measures a
  catalog-internal discrimination gap, and retains raw cosine only as an explicitly uncalibrated metric.
- Catalog-relative empirical support uses leave-one-out within-creator scores and cross-creator
  negatives. High tiers are unavailable when the profile/cohort is too small; a tiny catalog cannot
  manufacture a high-confidence creator attribution.
- Content-confound control: SSCD copy/content similarity is measured alongside CSD style similarity.
  Strong style with weak content can support a cross-content style review; SSCD never acts as a style veto.
- Corroborated style fusion combines learned style similarity, mark-making/texture mechanics,
  bidirectional tile consistency, content separation, catalog margin, and profile reliability. The result
  is an evidence index—not an infringement probability.
- Optional experimental CSD ViT-L style descriptor adapter. The CSD repository/checkpoint stays
  external; current upstream checkpoint uncertainty is surfaced instead of hidden.
- Always-available transparent style fallback using palette, luminance, edge-orientation, and texture
  distributions. Its evidence packet says `learned=false`; it is not passed off as AI attribution.
- Fail-closed SIFT-first / ORB-fallback local verification using mutual ratio-filtered matches, USAC/MAGSAC homography,
  minimum inlier support, two-sided spatial coverage/dispersion, symmetric transfer error, and
  homography sanity gates.
- Alignment-conditioned perceptual corroboration after geometry: luminance correlation, gradient
  correlation, gradient-magnitude similarity, local structural similarity, overlap, and a conservative
  geometric-mean structure consensus. Colour is descriptive and cannot veto a transformed copy.
- Corroborated fusion: SSCD is no longer a single threshold veto. Strong local/structural evidence can
  verify a near duplicate even when SSCD is below the old 0.75 threshold; high global similarity without
  local corroboration remains review-only.
- Global-to-pairwise verification re-ranking: retrieval rank is preserved for audit, while final evidence
  rank can promote a lower global candidate that actually verifies.
- Evidence Microscope with `Case summary`, `AI origin`, `Copy regions`, `Aligned structure`,
  `Creator profile`, and `Style map`. Misleading raw pixel-difference/overlay modes are absent.
- Model-hardened v0.10.0 workbench: source coverage, one bottom line, three clickable question cards, a strong analysis
  sidebar, active-view briefing panels, and purposeful colour separation between origin, copy, and style.
- Origin detail uses progressive disclosure: a plain conclusion, next action, two understandable
  scores, and three supporting facts are visible immediately; provider ledgers, calibration, and
  reason codes stay collapsed.
- Precision annotation patches: validated inliers are localized into compact support envelopes
  instead of one global convex hull. Each stored correspondence carries its transfer error, and the
  UI hides cross-image connection lines until hover/pin unless the user explicitly enables all lines.
- Authenticated reference-media proxy, so the side-by-side reference still renders for works
  registered earlier or elsewhere instead of relying on a browser-local object URL.
- Optional OpenRouter evidence explainer. It receives structured metrics, not images, and cannot
  change retrieval, verification, match status, or policy.
- Explicit, uncalibrated evidence fusion with abstention semantics. Its evidence index is never labelled a probability.
- Rights/policy evaluation kept separate from visual evidence.
- Claim-state authorization: only corroborated records can produce a rights-based pass.
- Deterministic, hashable Evidence Packets with typed coverage, catalog manifests, immutable
  ModelBundle identity, provenance trust facts, policy inputs, replay-trace digests, and limitations.
- Payload-bound idempotent scan creation with typed conflict responses.
- Local object storage for development; short-lived scan candidate retention.
- Non-blocking, single-worker local scan queue for zero-infrastructure development. The POST request
  returns a scan ID immediately; persisted stage progress is available through the normal scan GET.
- Batched external-origin adapter: all delivery and spatial views run in one GRIP process instead of
  reloading roughly 270 MB of weights once per view. Legacy one-image adapters share one deadline.
- Whole-scan OCR budget and capped external-detector budget prevent per-view timeout multiplication.
- Three-minute browser polling budget with a recoverable **Check again** action; no endless spinner.
- Inline execution is restricted to deterministic tests. An older development `.env` containing
  `CREATORPROOF_JOB_BACKEND=inline` is safely migrated to the local-thread runtime.
- Redis queue + dedicated worker path for Docker Compose.
- PostgreSQL production-shaped persistence in Docker Compose.
- Next.js dashboard with server-side API proxy; the API key is not sent to browser JavaScript.
- Official `c2patool` provenance adapter with trusted/untrusted/invalid/absent states.
- Verifiable RFC 6962-style local Merkle transparency receipts, explicitly labelled not blockchain.
- Optional real Ethereum Attestation Service on-chain receipts that commit only the canonical packet
  SHA-256 through a `bytes32 packetHash` schema, plus durable batched checkpoint anchors for signed
  registration and rights/status history. Final success requires full attestation binding and the
  configured confirmation depth.
- Benchmark promotion gates: tiny copy/style/origin runs are labelled `SMOKE_TEST_ONLY` rather than
  being misreported as production evidence.

## What is intentionally not faked

The repository does not pretend SSCD, a learned style model, or an AI-origin detector ran when it did
not. Model artifacts
are downloaded separately and the Evidence Packet records provider/fallback state on every scan. It
also does not bundle C2PA trust material, LightGlue-family weights, external detector repositories,
or blockchain credentials. A local Merkle receipt is never relabelled as a chain transaction.

The checked-in Part 1 ModelBundle is `RUNTIME_READY`, not `DEMO_READY`.
The selected external artifact bytes, application source, runtime lock, Python/package
environment, and optional requirement declarations are pinned, but authorized benchmark media,
calibration reports, profile consent, immutable build identity, and model/data terms must be
completed before stronger qualification. The Model Lab,
corpus validators, benchmark report identities, stable Part 2 fixtures, and no-media preflight are
under `apps/api/model_lab`, `apps/api/benchmarks`, and `apps/api/docs/part1`.

## Quick start - zero infrastructure

Requirements: Python 3.12+, `uv`, Node.js 20.9+, and Tesseract OCR with English language data.

On Ubuntu/Debian, install the visible-label dependency first:

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-eng
```

Backend:

```bash
cd apps/api
uv sync --dev
cp ../../.env.example .env
uv run uvicorn app.main:app --reload --port 8000
```

That starts the safe baseline. To activate the actual learned SSCD retrieval path:

```bash
cd apps/api
uv pip install -r requirements-ai.txt
uv run --no-sync python scripts/fetch_sscd_model.py --metadata-output models/sscd-fetch.json
uv run --no-sync python -m scripts.check_ai
uv run --no-sync uvicorn app.main:app --reload --port 8000
```

`check_ai` must report `available: true`, a 512-element descriptor, and a unit-length output before
you call the demo "AI retrieval active". Model loading is local and needs no API key.

The style lane works immediately with its transparent diagnostic fallback. To experiment with CSD as
the learned creator-profile resemblance provider:

```bash
cd apps/api
uv pip install -r requirements-style-experimental.txt
uv run --no-sync python -m scripts.fetch_csd_runtime
uv run --no-sync python -m scripts.check_style_ai --require-learned
```

PyTorch 2.6+ may reject the legacy checkpoint in safe-loading mode. The fetch command prints the exact
SHA-256 and the two opt-in environment settings needed for legacy loading. Never enable legacy pickle
loading without pinning and verifying that digest.

Do not skip the style benchmark. CSD's upstream repository currently warns about a weight discrepancy,
and 2026 research also shows raw CSD cosine should not be treated as a universal calibrated score.
See `docs/STYLE_SIMILARITY_AND_ATTRIBUTION.md`.

To make Sightengine the primary AI-origin detector, put the API user and secret in the private
`creatorproof/.env` file (never `.env.example`):

```dotenv
CREATORPROOF_SYNTHETIC_DETECTOR=auto
CREATORPROOF_SIGHTENGINE_API_USER=your-api-user
CREATORPROOF_SIGHTENGINE_API_SECRET=your-api-secret
```

The API uploads the original accepted image directly to Sightengine once. The response is recorded
as a vendor model signal, not a probability, signed provenance, or legal conclusion. Authentication,
quota, timeout, network, service, and invalid-response failures are the only conditions that activate
the local fallback. See `apps/api/docs/part1/SIGHTENGINE-PRIMARY-DETECTION.md`.

To provision the first open local AI-origin fallback:

```bash
cd apps/api
uv pip install -r requirements-synthetic.txt
uv run --no-sync python -m scripts.fetch_community_forensics_model
uv run --no-sync python -m scripts.check_synthetic_ai
```

The official model is loaded from safetensors. `check_synthetic_ai` proves that the runtime is active
and deterministic; it does not prove accuracy. Use `scripts.benchmark_synthetic_detection` and a
generator-disjoint manifest for that.

For the recommended second evidence family, clone the official Apache-2.0 GRIP repository, pull its
Git-LFS weights, and configure the included `scripts.clipdet_json_adapter`. The exact command is in
`.env.example` and the archived detector-activation details in `MASTER_EXECUTION_PROMPT_v0.9.1.md`.
The command must use `{manifest}`, not
`{image}`, so all views are evaluated in one upstream run. Do not call a low result “human” unless two
independent, held-out-calibrated families support the quiet decision.

Install the official `c2patool` separately to enable Content Credentials inspection. With no manifest,
the Evidence Packet remains origin-unknown.

Local Merkle receipts work without extra dependencies. For an optional real EAS testnet anchor:

```bash
cd apps/api
uv sync --frozen --extra blockchain
```

Then follow `docs/BLOCKCHAIN_IMPLEMENTATION_AND_DEPLOYMENT.md` to register separate packet and
checkpoint schemas, configure independent issuer/deployment pins, and pass the live acceptance gate.
Only an actually mined, data-bound, canonical, sufficiently confirmed EAS receipt is shown as a
public blockchain anchor.

Important activation boundary: a fresh clone and the supplied development `.env` do **not** write
to a public blockchain. `PROOF_ANCHOR_MODE=auto` with no schema UID and signer key deliberately
selects the local signed Merkle log. PostgreSQL/SQLite remains the operational store in either mode;
EAS stores only 32-byte packet commitments and batched signed checkpoint roots. Before describing a
deployment as blockchain-active, run the fail-closed check and retain its non-secret JSON output:

```bash
cd apps/api
uv run --no-sync python -m scripts.blockchain_acceptance
```

It succeeds only when the live deployment is explicit EAS/chain-required and both a direct scan
packet and a lifecycle checkpoint from the current deployment reverify against the configured chain.

Frontend, in a second terminal (the supplied `.env.local` already contains safe blank OpenRouter
placeholders):

```bash
cd apps/web
npm install
npm run dev
```

If you want the optional natural-language Evidence Explainer, set `OPENROUTER_API_KEY` in
`apps/web/.env.local`. `OPENROUTER_MODEL` may be set explicitly; leaving the key blank disables only
the explainer, not detection.

Open `http://localhost:3000`.

Before testing, confirm the page says `CreatorProof v0.10.0`. For the copy-AI demo, confirm the runtime
ledger reports the expected SSCD provider; fallback state remains explicit. For the learned style demo,
separately require the learned style provider state.

## Full local stack

If Docker Compose is installed:

```bash
cp .env.example .env
docker compose up --build
```

This runs web, API, Redis worker, PostgreSQL, and Redis. The development key is deliberately obvious; replace it before exposing the service.
Compose passes the private Sightengine variables to both API and worker without baking them into an
image or exposing them to browser JavaScript.

## Verify

```bash
cd apps/api
uv run --no-sync python -m scripts.validate_model_bundle
uv run --no-sync python -m scripts.preflight_part1
uv run pytest
uv run ruff check app tests scripts
uv run ruff format --check app tests scripts

cd ../web
npm run typecheck
npm run build
```

For a real timing record with the configured model artifacts, run:

```bash
cd apps/api
uv run python -m scripts.benchmark_scan_latency /absolute/path/to/test-image.png \
  --api-url http://localhost:8000 --api-key change-me-before-sharing
```

The output separates request-acceptance time from background processing time and records every
persisted stage transition. Source-only tests prove one batch invocation; only this target-machine
run can establish the actual latency of your CPU/GPU and model checkpoints.

## Demo flow

1. Register at least three works for one creator using the exact same **Creator profile** value,
   plus works for at least one other creator in the same catalog. Leave claim state `ASSERTED` for
   unverified records; use `CORROBORATED` only for the explicit demo/admin verified case.
2. Scan an unregistered crop/rescale/recompression/retouch of one reference. Confirm the expected work
   is the final verification rank `#1` and appears side-by-side; its original retrieval rank remains visible.
3. Inspect SSCD, pHash, geometry quality, aligned-structure consensus, evidence tier, policy outcome,
   and packet hash. Do not interpret the evidence index as an infringement probability.
4. Scan a genuinely unrelated image. A nearest registered reference will still be shown (nearest is
   mathematically unavoidable in a non-empty catalog), but it should say `NEAREST_CANDIDATE_ONLY`
   and draw **no** invented correspondence region unless robust geometry genuinely verifies.
5. Scan a genuinely different composition that is a labelled held-out positive for one creator's
   style. Copy geometry may correctly reject it; the separate Style resemblance card can still report
   `HIGH` and recommend review.
6. Open `Style field · diagnostic`. It should show tile-level low-level style diagnostics without any
   geometric pair lines or pixel-difference claim.
7. Inspect the independent AI-origin lane. The default view must show a clear conclusion, next action,
   AI signal, evidence quality, visible-label state, Content Credentials, and plain supporting facts.
   Open advanced details only to audit members, raw signals, disagreement, calibration, and abstention.
8. Run `python -m scripts.benchmark_copy_fusion` on a labeled held-out pair manifest and
   `python -m scripts.benchmark_style_retrieval` on a creator-disjoint style manifest before claiming an
   accuracy level. The style benchmark compares raw pool cosine with CSD+ CSLS and reports ROC-AUC,
   retrieval accuracy, discrimination gaps, and dataset-specific EER operating points.
9. Run `python -m scripts.benchmark_synthetic_detection` on generator-disjoint real/AI data and report
   FPR@95TPR, TPR@1%FPR, abstention, selective accuracy, confidence intervals, and worst groups.

There is deliberately no promise of "perfect accuracy": no image-retrieval model can honestly make
that guarantee on arbitrary unseen media. The included evaluation path is how you measure whether
your chosen operating point is good enough for the target customer corpus.

Start with `../MODEL_ACCURACY_IMPLEMENTATION_BEFORE_AFTER.md` for the v0.10.0 model-system
changes, fixed generated-media stress result, and exact verification commands. Use
`V092_SEMANTIC_SAFETY_REPORT.md` for the earlier v0.9.2 coverage, idempotency, origin-policy,
claim-state, and terminology changes. Then use `docs/V09_ORIGIN_SCORE_AND_PRODUCT_UI.md` for the visible-label
architecture, score math, plain-language UI contract, and research-backed upgrade path.
Use `MASTER_EXECUTION_PROMPT_v0.9.md` only for the archived v0.9 model-activation baseline.
`V09_EXECUTION_REPORT.md` records exactly which checks ran in the packaging workspace.
Use `docs/V08_ORIGIN_DETECTION_AND_UI.md` and `MASTER_EXECUTION_PROMPT_v0.8.md` only when auditing the
historical v0.8 baseline.
See `docs/V07_RESEARCH_ARCHITECTURE.md` for the broader three-lane architecture and scope.
See `docs/V07_DETECTION_MATH.md` for the exact active equations and gates.
See `docs/V07_VALIDATION_PROTOCOL.md` for the evaluation and red-team contract.
See `docs/V07_REPOSITORY_PLAYBOOK.md` for the complete research/repository map and exact integration prompts.
Use `MASTER_EXECUTION_PROMPT_v0.7.md` only when auditing the historical v0.7 baseline.
See `docs/IMPLEMENTATION_STATUS.md` for the promotion gates from this prototype to the intended SOTA stack.
See `docs/V05_DETECTION_MATH.md` for the exact active equations, fusion gates, and calibration contract.
See `docs/V06_STYLE_EVIDENCE_MATH.md` for the active CSD+ readout, content control, fusion, and policy math.
See `docs/V06_RESEARCH_AND_MODEL_TOURNAMENT.md` for the primary-source model tournament and repo plan.
See `docs/V06_VALIDATION.md` for what this build proves locally and what still needs real-corpus validation.
See `docs/V05_RESEARCH_AND_REPO_MAP.md` for the expanded SSCD/DreamSim/DiffSim/IntroStyle/MATCHA/etc. research map.
See `docs/EVIDENCE_MICROSCOPE.md` for the visualization contract and UI behavior.
See `docs/AI_RETRIEVAL_AND_VALIDATION.md` for SSCD/OpenRouter setup and the effectiveness test.
See `docs/STYLE_SIMILARITY_AND_ATTRIBUTION.md` for the creator-profile resemblance architecture and benchmark.
See `docs/STYLE_RESEARCH_REPOS.md` for CSD/CSD+/ALADIN/GOYA/StyleDecoupler/WeART and the model tournament.
See `docs/ANNOTATION_UPGRADE_PATH.md` for the benchmark-gated XFeat/LightGlue/RoMaV2/SAM2 research lane.
See `docs/VALIDATION.md` for the exact handoff checks that were run and the remaining Docker acceptance check.
