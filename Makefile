# Judge-facing inference probes. Weights stay out of Git and are fetched
# against the SHA-256 values in apps/api/model_lab/cards/.

SSCD_SHA := 9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56
CF_SHA := b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387

.PHONY: inference inference-copy inference-origin inference-style

inference: inference-copy inference-origin

inference-copy:
	cd apps/api && uv pip install -r requirements-ai.txt
	cd apps/api && if [ ! -f models/sscd_disc_mixup.torchscript.pt ]; then \
		uv run --no-sync python scripts/fetch_sscd_model.py \
			--expected-sha256 $(SSCD_SHA) \
			--metadata-output models/sscd-fetch.json; \
	fi
	cd apps/api && uv run --no-sync python -m scripts.check_ai

inference-origin:
	cd apps/api && uv pip install -r requirements-synthetic.txt
	cd apps/api && if [ ! -f models/community-forensics-384/model.safetensors ]; then \
		uv run --no-sync python -m scripts.fetch_community_forensics_model \
			--expected-sha256 $(CF_SHA); \
	fi
	cd apps/api && uv run --no-sync python -m scripts.check_synthetic_ai

inference-style:
	cd apps/api && uv pip install -r requirements-style-experimental.txt
	cd apps/api && uv run --no-sync python -m scripts.fetch_csd_runtime
	cd apps/api && uv run --no-sync python -m scripts.check_style_ai --require-learned
