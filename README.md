# CreatorProof

A brand is about to publish an image. CreatorProof answers the three questions
that actually matter, with a separate model stack for each:

| Lane | Question | What runs |
| --- | --- | --- |
| Copy | Does this reuse a work already in the catalog, and where? | Meta SSCD retrieval + MAGSAC geometry |
| Origin | What evidence is there that a generative model was involved? | Community Forensics + C2PA + optional Sightengine |
| Profile | Does it resemble a registered creator’s body of work? | CSD style descriptors (optional) |

Policy (`PASS` / `REVIEW` / `BLOCK`) is applied **after** the evidence. The
models do not vote into one fake confidence score.

**Live demo:** [creatorproof.uaenorth.cloudapp.azure.com](https://creatorproof.uaenorth.cloudapp.azure.com/)
· **v0.10.0** · **Models and how to run them:** [MODELS.md](MODELS.md)

---

## Models

These are trained, published checkpoints — the same class of models used in
copy-detection and AI-image research — wired into one review pipeline. Weights
are fetched from the official sources and checked against a pinned SHA-256.
That is how a clone gets the same inference the demo runs.

| Lane | Model | What CreatorProof adds | Code |
| --- | --- | --- | --- |
| Copy retrieve | SSCD DISC Mixup, 512-d | Regional query, ranking vs a declared catalog | [`ai_retrieval.py`](apps/api/app/providers/ai_retrieval.py) |
| Copy verify | OpenCV MAGSAC + aligned structure | A high SSCD score cannot MATCH without geometry | [`geometry.py`](apps/api/app/providers/geometry.py) |
| Origin | Community Forensics ViT-S/384 | Official 440→384 crop, fusion, abstention | [`synthetic_detection.py`](apps/api/app/providers/synthetic_detection.py) |
| Style | CSD ViT-L | Consent-backed profiles; diagnostic fallback if CSD is off | [`style_retrieval.py`](apps/api/app/providers/style_retrieval.py) |

Cards, hashes, and bundle identity: [`apps/api/model_lab/`](apps/api/model_lab/).

---

## Run the models

Python 3.12+ and [uv](https://docs.astral.sh/uv/). From this directory:

```bash
make inference
```

Downloads pinned SSCD and Community Forensics weights, then probes them:

```text
check_ai:              available true · 512-d unit vector · repeat similarity ~1.0
check_synthetic_ai:    Community Forensics loaded · deterministic probe
```

Full app (API + UI):

```bash
cp .env.example .env
cd apps/api && uv sync --dev && uv run uvicorn app.main:app --reload --port 8000
cd apps/web && npm install && npm run dev   # second terminal
```

Open `http://localhost:3000`. Longer setup: [DEVELOPER_SETUP_GUIDE.md](DEVELOPER_SETUP_GUIDE.md).

`make inference-style` is optional (CSD).

---

## Layout

```text
MODELS.md                 model catalog, preprocessing, validation
apps/api/app/providers/   inference
apps/api/app/services/    fusion, evidence packets, policy
apps/api/model_lab/       cards and SHA pins
apps/api/scripts/         fetch / check / benchmark
apps/web/                 reviewer and artist UI
```

Scope is the catalog you registered, not the open web. Scores are evidence
indexes, not legal conclusions.
