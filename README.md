# CreatorProof

Pre-publication check for a single image against a **declared catalog**.

A reviewer is about to publish something and asks “is this safe?” That is three
different questions, so this system runs three independent evidence lanes and
keeps policy (`PASS` / `REVIEW` / `BLOCK`) out of the models.

| Lane | Question | Does **not** decide |
| --- | --- | --- |
| Copy | Does this reuse a registered work, and where? | Copyright infringement |
| Origin | What evidence is there of generative AI? | “This is human-made” |
| Profile | Does it resemble a consenting creator’s body of work? | Authorship or ownership |

v0.10.0 · live demo: [creatorproof.uaenorth.cloudapp.azure.com](https://creatorproof.uaenorth.cloudapp.azure.com/)

**Judges: start at [MODELS.md](MODELS.md).** That page is the model catalog, the
preprocessing, what we wrote, and how to reproduce
inference.

---

## Models at a glance

Weights are **not** in Git. Each artifact is fetched from its official source and
checked against a pinned SHA-256.

| Role | Artifact | We wrote | Code |
| --- | --- | --- | --- |
| Copy retrieval | Meta SSCD `sscd_disc_mixup` (512-d) | Adapter, regional query, fusion gates | `apps/api/app/providers/ai_retrieval.py` |
| Copy verify | OpenCV MAGSAC + aligned structure | Fail-closed geometry and corroboration | `apps/api/app/providers/geometry.py` |
| AI origin | Community Forensics ViT-S/384 | Official 440→384 crop, fusion, abstention | `apps/api/app/providers/synthetic_detection.py` |
| Style (optional) | CSD ViT-L | Consent profiles, diagnostic fallback | `apps/api/app/providers/style_retrieval.py` |

Identity, hashes, and limits: [`apps/api/model_lab/`](apps/api/model_lab/).

---

## Reproduce inference (CPU)

Python 3.12+, [uv](https://docs.astral.sh/uv/). From this directory:

```bash
make inference
```

That installs the AI extras, downloads the pinned SSCD and Community Forensics
weights, and runs the smoke probes. Success looks like:

```text
check_ai:              available true, 512-d unit vector, repeat similarity ~1.0
check_synthetic_ai:    Community Forensics provider loaded, deterministic probe
```

If weights are missing, the API still runs and records an explicit pHash /
diagnostic fallback. It will not pretend SSCD ran.

CSD style weights are optional and experimental (`make inference-style`). Skip
them unless you need that lane.

Full local app (API + Next.js) is in [DEVELOPER_SETUP_GUIDE.md](DEVELOPER_SETUP_GUIDE.md).
Short version:

```bash
cp .env.example .env
# terminal 1
cd apps/api && uv sync --dev && uv run uvicorn app.main:app --reload --port 8000
# terminal 2
cd apps/web && npm install && npm run dev
```

Open `http://localhost:3000`.

---

## Layout

```text
MODELS.md                 ← model catalog for this submission
apps/api/app/providers/   ← inference adapters
apps/api/app/services/    ← fusion, packets, policy (after evidence)
apps/api/model_lab/       ← cards, SHA pins, qualification state
apps/api/scripts/         ← fetch_*, check_*, benchmark_*
apps/web/                 ← reviewer / artist UI
docs/                     ← math and research notes
archive/                  ← old prompts and release logs
```

---

## What this build will not claim

- It does not search the open web. Scope is the catalog you registered.
- Detector scores are evidence indexes, not probabilities.
- Local Merkle receipts are labelled not-blockchain. A public EAS anchor is
  optional and only shown when a transaction actually confirms.
- The checked-in bundle is `RUNTIME_READY`: the pinned bytes load. It is not a
  calibrated production accuracy claim.
