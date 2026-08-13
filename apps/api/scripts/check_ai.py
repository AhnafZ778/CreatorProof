from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.config import Settings
from app.providers.ai_retrieval import SSCDVisualEmbeddingProvider
from app.services.model_bundle import load_model_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify that CreatorProof SSCD inference runs.")
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("models/sscd_disc_mixup.torchscript.pt"),
    )
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    args = parser.parse_args()
    settings = Settings()
    bundle = load_model_bundle(
        settings.model_bundle_path,
        strict=settings.model_bundle_strict,
    )
    provider = SSCDVisualEmbeddingProvider(
        args.model,
        args.device,
        expected_sha256=(
            settings.sscd_expected_sha256 or bundle.declared_artifact_sha256("copy-retrieval-sscd")
        ),
    )
    if not provider.available:
        raise SystemExit(json.dumps(provider.status(), indent=2))

    pixels = np.zeros((288, 384, 3), dtype=np.uint8)
    pixels[40:220, 60:170] = (30, 190, 230)
    pixels[90:250, 220:340] = (240, 145, 35)
    image = Image.fromarray(pixels)
    vector = provider.embed(image)
    repeated = provider.embed(image.copy())
    print(
        json.dumps(
            {
                **provider.status(),
                "model_bundle": bundle.status(),
                "embedding_dimensions": int(vector.shape[0]),
                "embedding_l2_norm": round(float(np.linalg.norm(vector)), 6),
                "repeat_similarity": round(provider.similarity(vector, repeated), 6),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
