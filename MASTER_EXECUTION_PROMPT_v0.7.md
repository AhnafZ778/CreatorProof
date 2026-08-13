# CreatorProof v0.7 — master agentic execution prompt

Copy everything below into an agentic IDE opened at the extracted `creatorproof` repository root.

---

You are the lead engineer and validation owner for **CreatorProof v0.7.0**, build signature
`TRI-LANE-PROVENANCE-2026.08.09`. Work autonomously, but do not fabricate successful commands,
model activation, benchmark results, blockchain transactions, or browser observations.

## Product invariants

CreatorProof answers three independent questions:

1. Is there evidence the candidate was AI-generated or AI-assisted?
2. Is there corroborated evidence that a particular registered work was reused?
3. Does a different-content candidate unusually resemble a registered creator's multi-work style
   profile?

Never collapse these into an “infringement probability.” Never claim perfect AI detection, proof of
training-data use, creator authorship from one exemplar, or legal infringement. A missing C2PA
manifest is unknown origin, not human origin. Style cannot manufacture `MATCH_FOUND`. A local Merkle
receipt is not blockchain. Only a mined, valid EAS receipt is an on-chain anchor.

## Phase 0 — inspect without destroying work

1. Read `README.md`, `BUILD_INFO.md`, `.env.example`, `docs/V07_RESEARCH_ARCHITECTURE.md`,
   `docs/V07_DETECTION_MATH.md`, `docs/V07_VALIDATION_PROTOCOL.md`, and
   `docs/V07_REPOSITORY_PLAYBOOK.md` completely.
2. Read any `AGENTS.md` files that govern files you touch.
3. Inspect repository status and preserve existing user changes. Do not reset, delete, or overwrite
   unrelated work.
4. Record OS, Python, `uv`, Node, npm, and optional Docker versions.
5. Search for secrets before printing environment files. Never print API/private keys.

## Phase 1 — create configuration safely

Backend:

```bash
cd apps/api
cp -n ../../.env.example .env
```

Frontend:

```bash
cd ../web
test -f .env.local || cp .env.local.example .env.local
```

If `apps/web/.env.local.example` is absent, create `.env.local` with only:

```dotenv
CREATORPROOF_API_URL=http://localhost:8001
CREATORPROOF_API_KEY=change-me-before-sharing
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
```

Do not invent an OpenRouter key. A blank key disables only the optional language explainer.

## Phase 2 — install core dependencies

From `apps/api`:

```bash
uv sync --dev
```

From `apps/web`:

```bash
npm install
```

Use the repository lockfiles. Report any runtime-version incompatibility instead of silently changing
major framework versions.

## Phase 3 — activate learned copy retrieval

From `apps/api`:

```bash
uv pip install -r requirements-ai.txt
uv run --no-sync python scripts/fetch_sscd_model.py
uv run --no-sync python -m scripts.check_ai
```

Acceptance:

- provider is `sscd-disc-mixup-torchscript`;
- `available` is true;
- embedding dimension is 512;
- L2 norm is approximately 1;
- repeat similarity is approximately 1;
- model SHA-256 is recorded.

If download/network is unavailable, report SSCD inactive and preserve the explicit fallback. Do not
claim it ran.

## Phase 4 — activate learned creator-style retrieval

From `apps/api`:

```bash
uv pip install -r requirements-style-experimental.txt
uv run --no-sync python -m scripts.fetch_csd_runtime
uv run --no-sync python -m scripts.check_style_ai --require-learned
```

Keep legacy pickle loading disabled by default. If the official CSD checkpoint requires the explicit
legacy path, first record the downloaded file SHA-256, compare it with an independently expected
digest, set both:

```dotenv
CREATORPROOF_STYLE_ALLOW_LEGACY_PICKLE=true
CREATORPROOF_STYLE_CSD_EXPECTED_SHA256=<exact digest>
```

Never enable `weights_only=False` for an unpinned or user-supplied checkpoint.

Acceptance:

- learned provider active;
- embedding is finite, non-zero, deterministic, and L2-normalized;
- checkpoint SHA-256 is reported;
- calibration state does not pretend a provider check is an accuracy benchmark.

## Phase 5 — activate AI-origin detection

From `apps/api`:

```bash
uv pip install -r requirements-synthetic.txt
uv run --no-sync python -m scripts.fetch_community_forensics_model
uv run --no-sync python -m scripts.check_synthetic_ai
```

Acceptance:

- `community-forensics-vit-small-384` is active;
- official safetensors are used; no pickle checkpoint is loaded;
- repeated inference is deterministic within tolerance;
- provider, model version, device, and weight SHA-256 are recorded;
- the diagnostic image's score is explicitly not treated as an accuracy test;
- calibration is either a valid model-version-matched held-out calibration or clearly unavailable.

Optional authorized detector adapters can be configured through
`CREATORPROOF_SYNTHETIC_EXTERNAL_DETECTORS_JSON`. Each command must contain `{image}`, run without a
shell, print one JSON object, and identify its provider/version. Do not clone or bundle repositories
whose license has not been cleared; use an operator-supplied external installation.

## Phase 6 — install provenance and proof runtimes

### C2PA

Install an official `c2patool` release using the platform's normal package/release mechanism. Record
its version. Do not substitute a home-grown manifest parser.

Run:

```bash
c2patool --version
```

If unavailable, the health endpoint must say provenance unavailable. Missing tooling must not crash
scans.

### Local proof

No extra package is required. Default `auto` mode falls back to the local Merkle transparency log
when EAS credentials are incomplete.

### Optional real EAS testnet anchor

```bash
uv pip install -r requirements-blockchain.txt
```

Configure the following only with operator-provided testnet values:

```dotenv
CREATORPROOF_PROOF_ANCHOR_MODE=eas
CREATORPROOF_EAS_RPC_URL=<testnet RPC>
CREATORPROOF_EAS_CONTRACT_ADDRESS=<official network EAS contract>
CREATORPROOF_EAS_SCHEMA_UID=<schema UID for exactly: bytes32 packetHash>
CREATORPROOF_EAS_PRIVATE_KEY=<funded disposable testnet signer>
CREATORPROOF_EAS_RECIPIENT=0x0000000000000000000000000000000000000000
CREATORPROOF_EAS_EXPLORER_TX_BASE_URL=<explorer tx base URL>
# Optional; otherwise read from RPC
CREATORPROOF_EAS_CHAIN_ID=<chain id>
```

Do not print the private key. Do not use mainnet funds. Do not put artwork, identity, or raw evidence
on-chain. The only schema value is the packet's `bytes32` SHA-256 commitment.

Acceptance for “blockchain active”:

- transaction is mined successfully;
- Attested event yields an attestation UID;
- `isAttestationValid(uid)` returns true;
- returned packet hash matches the local canonical packet;
- chain ID, transaction hash, block number, schema UID, and explorer URL are present.

Otherwise call it a local transparency receipt, not blockchain.

## Phase 7 — quality gates

Backend:

```bash
cd apps/api
uv run ruff check app tests scripts
uv run ruff format --check app tests scripts
uv run pytest -q
```

Frontend:

```bash
cd ../web
npm run typecheck
npm run build
```

Fix real issues and rerun the complete affected gate. Do not weaken assertions merely to make a test
green. Do not replace calibrated/fail-closed behavior with permissive thresholds.

## Phase 8 — start clean services

Check whether ports 8001 and 3001 are already occupied. Stop only processes proven to be the current
CreatorProof development services; do not use broad destructive process kills.

Backend terminal:

```bash
cd apps/api
uv run --no-sync uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Frontend terminal:

```bash
cd apps/web
CREATORPROOF_API_URL=http://127.0.0.1:8001 npm run dev -- --port 3001
```

Health checks:

```bash
curl -fsS http://127.0.0.1:8001/healthz
curl -fsS http://127.0.0.1:3001/api/health
```

Require version `0.7.0` and build signature `TRI-LANE-PROVENANCE-2026.08.09`. Record separate states
for SSCD, learned style, synthetic-origin ensemble, C2PA, and proof provider.

## Phase 9 — end-to-end acceptance corpus

Use only images you are authorized to test. Do not place the test images in the repository or final
archive.

Register:

- at least 3 diverse works for target creator A;
- at least 3 works each for multiple other creators;
- at least 19 cross-creator reference works total if you expect a possible style `VERY_HIGH` tier;
- one catalog ID shared by the test.

Execute and record:

### Case A — retouched near-copy

- candidate is a crop/resize/JPEG/colour touch-up of one registered work;
- correct source should reach verification rank 1;
- geometry must validate;
- aligned structure must be available and supportive;
- `MATCH_FOUND` is allowed only through exact hash or geometry + aligned-structure gates;
- side-by-side source must render.

### Case B — unrelated hard negative

- nearest candidate is shown as retrieval context;
- no unvalidated correspondence lines or support regions are displayed;
- no `MATCH_FOUND`;
- UI states that nearest does not mean match.

### Case C — same creator, different content

- correct creator profile should rank highly only if the held-out label supports it;
- copy lane should stay negative unless there is actual same-work reuse;
- high style tiers require catalog calibration support;
- content confound and false-match tail must be visible.

### Case D — AI-generated style imitation

- origin lane reports C2PA and detector evidence separately;
- copy lane remains negative for a genuinely new composition;
- calibrated style lane may be high;
- combined banner becomes `AI_STYLE_RESEMBLANCE_REVIEW` only when both origin and style support exist;
- UI never says “infringing.”

### Case E — transform-unstable detector

Use a controlled test stub if necessary. Force detector scores to vary strongly across the robustness
views. Require `INCONCLUSIVE_TRANSFORM_INSTABILITY`, not a confident AI/human label.

### Case F — no detector and no C2PA

Require `SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE` or an equivalent unknown state. Never infer human.

## Phase 10 — benchmark honesty

Run copy, retrieval, style, and AI-origin benchmark scripts against available labeled manifests. If a
manifest is tiny, the report must say `SMOKE_TEST_ONLY`. Do not publish 100% accuracy from a handful
of examples.

For AI-origin evaluation require ROC-AUC, average precision, FPR@95TPR, TPR@1%FPR, abstention,
selective coverage/accuracy, confidence interval, and per-generator/source groups.

For style require creator-disjoint positives, same-movement hard negatives, profile-size slices,
false-accept metrics, and conformal support. For copy require transformed positives and repeated-
pattern/same-subject/same-creator hard negatives.

## Phase 11 — browser and UI verification

Open `http://127.0.0.1:3001` and inspect desktop and 375 px mobile layouts.

Verify:

1. top workflow navigation is obvious;
2. register and scan cards have distinct colour/action hierarchy;
3. results immediately show three independent verdict cards;
4. combined triage banner is visible before detailed charts;
5. left analysis rail exposes six numbered modes;
6. active mode is unmistakable;
7. AI-origin view shows candidate, C2PA state, detector count, stability, disagreement, and member
   ledger;
8. copy regions hide rejected/fake annotations;
9. aligned structure explains metrics and never shows a raw pixel-difference heatmap as truth;
10. creator style shows catalog calibration state, negative-tail value, positive support percentile,
    content control, and reference count;
11. style map is labelled diagnostic, not copied regions;
12. proof panel says local-not-blockchain or links a real EAS transaction;
13. no horizontal overflow or unreadable oversized spacing exists;
14. keyboard focus and buttons remain usable.

Capture screenshots only into a temporary validation folder, not the distributable codebase.

## Phase 12 — final execution report

Write `V07_EXECUTION_REPORT.md` with:

- exact versions and build signature;
- commands run and actual exit status;
- provider/model activation and hashes;
- test/build results;
- each E2E case's raw metrics and decision;
- benchmark sample counts, split strategy, confidence intervals, and grade;
- UI/browser checks;
- proof mode and verifiability;
- known limitations and failed/blocked checks;
- a final verdict chosen from `RUNTIME_READY`, `DEMO_READY`, `DOMAIN_CALIBRATED`, or
  `PRODUCTION_MONITORED`.

Do not use `PRODUCTION_READY` merely because builds pass. Do not write “100% accurate” or “perfect.”

## Final response format

Lead with the real outcome. Include:

1. overall promotion level;
2. tests/builds that passed;
3. active versus unavailable model/provenance/proof providers;
4. E2E case summary;
5. the three most important remaining empirical risks;
6. exact URLs for frontend/backend;
7. paths to the execution report and any benchmark JSON.

If anything failed, say exactly what failed and keep the system in the lower honest promotion state.

---
