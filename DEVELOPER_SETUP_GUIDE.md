# CreatorProof — Developer & AI Agent Full Setup Guide

> **Target Build Signature:** `MODEL-ACCURACY-HARDENING-2026.08.10`  
> **Repository Root:** `/creatorproof`  
> **Backend Service:** FastAPI on `http://127.0.0.1:8000`  
> **Frontend Service:** Next.js (Turbopack) on `http://localhost:3000`  

This guide provides an end-to-end, automated setup specification designed for an AI agent or developer to configure a completely identical environment with all active detection lanes (SSCD visual copy retrieval, CSD style attribution, Community Forensics & Sightengine synthetic origin analysis, and Merkle proof anchoring).

---

## 1. System Requirements & Prerequisites

Ensure the following system tools are installed on the host (Ubuntu/Debian commands shown):

```bash
# Core tools
sudo apt update && sudo apt install -y git git-lfs curl build-essential libgl1 libglib2.0-0

# Optional forensic OCR and C2PA tools
sudo apt install -y tesseract-ocr
# (Optional) c2patool binary can be installed from official releases if C2PA provenance extraction is needed.

# Python package manager (uv)
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Node.js (v20+ recommended)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

---

## 2. Environment Configuration Files

Create the following two environment files.

### A. Backend Configuration: `apps/api/.env`

Create `apps/api/.env` with the following content:

```env
# Core API Settings
CREATORPROOF_DEV_API_KEY=change-me-before-sharing
CREATORPROOF_DATABASE_URL=sqlite:///./creatorproof.db
CREATORPROOF_STORAGE_ROOT=./data
CREATORPROOF_JOB_BACKEND=local
CREATORPROOF_LOCAL_JOB_WORKERS=1
CREATORPROOF_REDIS_URL=redis://localhost:6379/0
CREATORPROOF_API_URL=http://localhost:8000

# SSCD Copy Retrieval Lane
CREATORPROOF_SSCD_MODEL_PATH=./models/sscd_disc_mixup.torchscript.pt
CREATORPROOF_SSCD_DEVICE=auto
CREATORPROOF_SSCD_MATCH_SIMILARITY=0.75
CREATORPROOF_SSCD_REVIEW_SIMILARITY=0.60

# Corroborated Copy Fusion Operating Points
CREATORPROOF_COPY_STRUCTURE_MATCH_SIMILARITY=0.76
CREATORPROOF_COPY_STRUCTURE_VERY_STRONG_SIMILARITY=0.84
CREATORPROOF_COPY_GEOMETRY_VERY_STRONG_QUALITY=0.72
CREATORPROOF_COPY_SSCD_SUPPORT_SIMILARITY=0.55
CREATORPROOF_COPY_GEOMETRY_SSCD_MATCH_SIMILARITY=0.70
CREATORPROOF_COPY_SSCD_VERY_STRONG_SIMILARITY=0.86
CREATORPROOF_COPY_STRUCTURE_SUPPORT_SIMILARITY=0.62
CREATORPROOF_COPY_PHASH_SUPPORT_SIMILARITY=0.78
CREATORPROOF_COPY_GLOBAL_REVIEW_SIMILARITY=0.80
CREATORPROOF_COPY_PHASH_REVIEW_SIMILARITY=0.90

# Creator Style Resemblance Lane (CSD)
CREATORPROOF_STYLE_PROVIDER=auto
CREATORPROOF_STYLE_CSD_REPO_PATH=./vendor/CSD
CREATORPROOF_STYLE_CSD_MODEL_PATH=./models/csd-vit-l/pytorch_model.bin
CREATORPROOF_STYLE_DEVICE=auto
CREATORPROOF_STYLE_TOP_K=5
CREATORPROOF_STYLE_CSLS_K=15
CREATORPROOF_STYLE_LEARNED_SUPPORT_SIMILARITY=0.68
CREATORPROOF_STYLE_MECHANICS_SUPPORT_SIMILARITY=0.70
CREATORPROOF_STYLE_TILE_SUPPORT_SIMILARITY=0.68
CREATORPROOF_STYLE_CONTENT_GAP_SUPPORT=0.12
CREATORPROOF_STYLE_CATALOG_MARGIN_SUPPORT=0.03
CREATORPROOF_STYLE_EVIDENCE_REVIEW_SIMILARITY=0.58
CREATORPROOF_STYLE_EVIDENCE_HIGH_SIMILARITY=0.74
CREATORPROOF_STYLE_EVIDENCE_VERY_HIGH_SIMILARITY=0.84
CREATORPROOF_STYLE_MIN_PROFILE_WORKS=3
CREATORPROOF_STYLE_MIN_CALIBRATION_PROFILES=3
CREATORPROOF_STYLE_MIN_CALIBRATION_NEGATIVES=19
CREATORPROOF_STYLE_HIGH_MAX_NEGATIVE_TAIL_P=0.10
CREATORPROOF_STYLE_VERY_HIGH_MAX_NEGATIVE_TAIL_P=0.05
CREATORPROOF_STYLE_HIGH_MIN_POSITIVE_PERCENTILE=0.25
CREATORPROOF_STYLE_VERY_HIGH_MIN_POSITIVE_PERCENTILE=0.50
CREATORPROOF_STYLE_ALLOW_LEGACY_PICKLE=true
CREATORPROOF_STYLE_CSD_EXPECTED_SHA256=40e92fad63a361b8136100cd234c42d401ef9b34ff1748234318929ebcc7e7a1

# Synthetic AI-Origin Lane
CREATORPROOF_SYNTHETIC_DETECTOR=auto
CREATORPROOF_SYNTHETIC_POLICY_MODE=INFORMATIONAL
CREATORPROOF_SIGHTENGINE_API_USER=
CREATORPROOF_SIGHTENGINE_API_SECRET=
CREATORPROOF_SIGHTENGINE_API_KEY=
CREATORPROOF_SIGHTENGINE_TIMEOUT_SECONDS=20
CREATORPROOF_SYNTHETIC_COMMUNITY_MODEL_PATH=./models/community-forensics-384
CREATORPROOF_SYNTHETIC_TORCHSCRIPT_MODEL_PATH=./models/synthetic-detector.torchscript.pt
CREATORPROOF_SYNTHETIC_DEVICE=auto
CREATORPROOF_SYNTHETIC_EXTERNAL_DETECTORS_JSON=[{"name": "grip-clipdet", "command": "python -m scripts.clipdet_json_adapter --manifest {manifest} --repo ./vendor/ClipBased-SyntheticImageDetection --weights ./vendor/ClipBased-SyntheticImageDetection/weights --runner-python ./vendor/ClipBased-SyntheticImageDetection/.venv/bin/python --device cpu", "timeout_seconds": 180, "evidence_family": "SEMANTIC_PIXEL_HYBRID", "source_scope": "CLIP_SEMANTIC_PLUS_FORENSIC_PIXEL_MODELS"}]
CREATORPROOF_SYNTHETIC_CALIBRATION_PATH=./models/synthetic-calibration.json
CREATORPROOF_SYNTHETIC_MIN_CALIBRATION_SAMPLES=100
CREATORPROOF_SYNTHETIC_MIN_CALIBRATION_CLASS_SAMPLES=25
CREATORPROOF_SYNTHETIC_LIKELY_THRESHOLD=0.78
CREATORPROOF_SYNTHETIC_REVIEW_THRESHOLD=0.58
CREATORPROOF_SYNTHETIC_MAX_VIEW_STD=0.18
CREATORPROOF_SYNTHETIC_MIN_SHORT_SIDE=128
CREATORPROOF_SYNTHETIC_SPATIAL_CROPS=true
CREATORPROOF_SYNTHETIC_SPATIAL_CROP_FRACTION=0.78
CREATORPROOF_SYNTHETIC_MIN_INDEPENDENT_FAMILIES=2

# Visible AI-Label OCR
CREATORPROOF_VISIBLE_AI_MARKER_MODE=auto
CREATORPROOF_VISIBLE_AI_MARKER_BINARY=tesseract
CREATORPROOF_VISIBLE_AI_MARKER_TIMEOUT_SECONDS=12
CREATORPROOF_VISIBLE_AI_MARKER_MIN_CONFIDENCE=0.42
CREATORPROOF_VISIBLE_AI_MARKER_TERMS_JSON=[]

# C2PA Provenance
CREATORPROOF_C2PA_MODE=auto
CREATORPROOF_C2PA_BINARY=c2patool
CREATORPROOF_C2PA_TIMEOUT_SECONDS=20

# Cryptographic Merkle Transparency Anchor
CREATORPROOF_PROOF_ANCHOR_MODE=auto
CREATORPROOF_PROOF_LOG_PATH=./data/proof-log.jsonl
CREATORPROOF_EAS_RPC_URL=
```

### B. Frontend Configuration: `apps/web/.env.local`

Create `apps/web/.env.local` with:

```env
CREATORPROOF_API_URL=http://localhost:8000
CREATORPROOF_DEV_API_KEY=change-me-before-sharing

# Optional server-side LLM explainer route
OPENROUTER_API_KEY=
OPENROUTER_MODEL=
OPENROUTER_SITE_URL=http://localhost:3000
```

---

## 3. Backend Virtual Environment & Dependencies

From the repository root:

```bash
cd apps/api

# Create venv and sync dependencies
uv sync

# Install PyTorch, torchvision, timm, and huggingface dependencies required by ML models
uv pip install torch torchvision timm safetensors huggingface-hub scipy clip git+https://github.com/openai/CLIP.git
```

---

## 4. Models & Pretrained Weights Setup

Create the models directory structure:

```bash
mkdir -p apps/api/models/community-forensics-384
mkdir -p apps/api/models/csd-vit-l
```

### Option A: Using Included Download Scripts (Automated)
```bash
cd apps/api

# 1. Fetch SSCD Copy Detection Model (~98 MB)
uv run python -m scripts.fetch_sscd_model

# 2. Fetch Community Forensics Synthetic Detector (~87 MB)
uv run python -m scripts.fetch_community_forensics_model

# 3. Fetch CSD Style Model & Runtime (~2.4 GB)
uv run python -m scripts.fetch_csd_runtime
```

### Option B: Direct File Locations
If copying existing assets directly from another machine:
* `apps/api/models/sscd_disc_mixup.torchscript.pt`
* `apps/api/models/community-forensics-384/model.safetensors` & `config.json`
* `apps/api/models/csd-vit-l/pytorch_model.bin`

---

## 5. Vendor Submodules & Repositories Setup

Place or clone the vendor detection modules into `apps/api/vendor/`:

```bash
mkdir -p apps/api/vendor
cd apps/api/vendor

# 1. Clone CSD (Style Detection)
git clone https://github.com/rotsteinnoam/CSD.git CSD

# 2. Clone GRIP Synthetic Detector with Git-LFS weights
git clone https://github.com/grip-unina/ClipBased-SyntheticImageDetection.git ClipBased-SyntheticImageDetection
cd ClipBased-SyntheticImageDetection
git lfs pull

# Setup dedicated venv for ClipBased detector
uv venv .venv
uv pip install -p .venv/bin/python torch torchvision scipy open_clip_torch pandas
cd ../../../
```

---

## 6. Database Migration & Schema Seeding

Initialize the SQLite database schema and apply Alembic migrations:

```bash
cd apps/api
# Apply migrations to create tables and baseline schema
uv run python -m scripts.migrate upgrade
```

---

## 7. Frontend Setup

Install Next.js dependencies:

```bash
cd apps/web
npm install
```

---

## 8. Verification & Pre-flight Diagnostics

Verify that all model lanes pass operational checks:

```bash
cd apps/api

# 1. Verify SSCD Visual Embedding
uv run python -m scripts.check_ai

# 2. Verify CSD Style Attribution
uv run python -m scripts.check_style_ai

# 3. Verify Synthetic AI Origin Detection
uv run python -m scripts.check_synthetic_ai
```

All three commands should print JSON diagnostics confirming `available: true` or active inference.

---

## 9. Starting the Development Servers

Run the backend and frontend in separate terminals (or detached processes):

### Terminal 1: Backend API (Port 8000)
```bash
cd apps/api
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Terminal 2: Frontend UI (Port 3000)
```bash
cd apps/web
npm run dev
```

### Running the frontend in production mode

`next.config.ts` sets `output: "standalone"`, so the built server lives at
`.next/standalone/server.js` rather than being launched by `next start`:

```bash
cd apps/web
npm run build   # also copies public/ and .next/static into .next/standalone
npm start       # node .next/standalone/server.js
```

The build's copy step is what makes this work. Next leaves `public/` and
`.next/static/` out of the standalone directory by design, and without them the
homepage 404s and every stylesheet and script fails to load.

---

## 10. Accessing the Application

Open your browser at:
👉 **`http://localhost:3000`**

- **Register Reference:** Register images into catalog `demo-catalog`.
- **Run Scan:** Upload candidate images to challenge the catalog and view the full **Evidence Microscope** breakdown with AI Origin, Copy Regions, Aligned Structure, Style Resemblance, and Merkle Proof receipts.

---

## 11. Troubleshooting

### Error: `sqlite3.DatabaseError: database disk image is malformed`
If a crash or interrupted write corrupts the local SQLite file:
```bash
cd apps/api
# Remove corrupted local sqlite db and journal files
rm -f creatorproof.db creatorproof.db-shm creatorproof.db-wal creatorproof.db.bak*
# Run migrations to generate a clean, initialized database
uv run python -m scripts.migrate upgrade --skip-backup
```

