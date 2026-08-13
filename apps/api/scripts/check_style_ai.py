from __future__ import annotations

import argparse
import json

import numpy as np
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.providers.style_retrieval import StyleEmbeddingRouter
from app.services.model_bundle import load_model_bundle


def _probe_image() -> Image.Image:
    image = Image.new("RGB", (256, 256), "#e9e1d2")
    draw = ImageDraw.Draw(image)
    for offset in range(0, 256, 18):
        draw.line((0, offset, 255, max(0, 255 - offset)), fill="#315b7a", width=5)
    draw.ellipse((75, 55, 205, 185), outline="#b45d43", width=9)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the configured creator-style provider.")
    parser.add_argument("--require-learned", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    bundle = load_model_bundle(
        settings.model_bundle_path,
        strict=settings.model_bundle_strict,
    )
    router = StyleEmbeddingRouter(
        mode=settings.style_provider,
        csd_repo_path=settings.style_csd_repo_path,
        csd_model_path=settings.style_csd_model_path,
        device=settings.style_device,
        allow_legacy_pickle=settings.style_allow_legacy_pickle,
        expected_sha256=(
            settings.style_csd_expected_sha256 or bundle.declared_artifact_sha256("style-csd")
        ),
        expected_repo_revision=settings.style_csd_expected_repo_revision,
    )
    image = _probe_image()
    first = router.embed(image)
    second = router.embed(image)
    batch = router.embed_many([image, image])
    status = router.status()
    status.update(
        {
            "embedding_dimensions": int(first.shape[0]),
            "embedding_l2_norm": round(float(np.linalg.norm(first)), 8),
            "repeat_similarity": round(router.similarity(first, second), 8),
            "batch_count": len(batch),
            "batch_repeat_similarity": round(router.similarity(batch[0], batch[1]), 8),
            "single_batch_similarity": round(router.similarity(first, batch[0]), 8),
            "calibration_state": "PROVIDER_CHECK_ONLY_NO_ACCURACY_CLAIM",
            "model_bundle": bundle.status(),
        }
    )
    print(json.dumps(status, indent=2))
    if args.require_learned and not status["learned"]:
        print("FAIL: learned style provider is not active.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
