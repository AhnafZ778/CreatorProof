from __future__ import annotations

import argparse
import json

import numpy as np
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.providers.style_retrieval import StyleEmbeddingRouter


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
    router = StyleEmbeddingRouter(
        mode=settings.style_provider,
        csd_repo_path=settings.style_csd_repo_path,
        csd_model_path=settings.style_csd_model_path,
        device=settings.style_device,
        allow_legacy_pickle=settings.style_allow_legacy_pickle,
        expected_sha256=settings.style_csd_expected_sha256,
    )
    image = _probe_image()
    first = router.embed(image)
    second = router.embed(image)
    status = router.status()
    status.update(
        {
            "embedding_dimensions": int(first.shape[0]),
            "embedding_l2_norm": round(float(np.linalg.norm(first)), 8),
            "repeat_similarity": round(router.similarity(first, second), 8),
            "calibration_state": "PROVIDER_CHECK_ONLY_NO_ACCURACY_CLAIM",
        }
    )
    print(json.dumps(status, indent=2))
    if args.require_learned and not status["learned"]:
        print("FAIL: learned style provider is not active.")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
