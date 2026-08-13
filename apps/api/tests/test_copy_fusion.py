from dataclasses import asdict

import cv2
import numpy as np
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.providers.aligned_perceptual import AlignedPerceptualVerifier
from app.providers.geometry import ORBGeometricVerifier
from app.services.copy_fusion import fuse_copy_evidence


def _structured_image() -> Image.Image:
    image = Image.new("RGB", (520, 340), "#e9edf0")
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 24, 496, 316), outline="#15202b", width=5)
    draw.rectangle((48, 58, 272, 112), fill="#2d6c9e")
    draw.ellipse((326, 62, 452, 188), fill="#b85c42", outline="#202830", width=4)
    draw.line((72, 152, 430, 276), fill="#18222b", width=8)
    for index in range(8):
        y = 188 + index * 13
        draw.line((66, y, 248 + index * 8, y), fill="#4b5b67", width=4)
    draw.text((58, 72), "CREATORPROOF 05", fill="white")
    return image


def _retouched_perspective(image: Image.Image) -> Image.Image:
    source = np.asarray(image, dtype=np.uint8)
    height, width = source.shape[:2]
    src = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    dst = np.float32([[8, 6], [width - 15, 2], [width - 5, height - 8], [14, height - 1]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(source, matrix, (width, height), borderValue=(235, 238, 240))
    # Strong colour/contrast shift approximates a retouch while retaining composition.
    lab = cv2.cvtColor(warped, cv2.COLOR_RGB2LAB)
    lab[:, :, 0] = np.clip(lab[:, :, 0].astype(np.float32) * 0.90 + 12, 0, 255).astype(np.uint8)
    transformed = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)
    return Image.fromarray(transformed)


def test_retouched_near_duplicate_is_corrobated_even_when_sscd_is_072():
    reference = _structured_image()
    query = _retouched_perspective(reference)
    geometry = asdict(ORBGeometricVerifier(max_features=3200).verify(query, reference))
    assert geometry["validated"] is True

    aligned = asdict(
        AlignedPerceptualVerifier().verify(
            query,
            reference,
            geometry["homography_query_to_reference"],
        )
    )
    assert aligned["available"] is True
    assert aligned["structure_consensus"] > 0.80

    fusion = fuse_copy_evidence(
        exact_sha256=False,
        ai_similarity=0.72,
        phash_similarity=0.93,
        geometry=geometry,
        aligned_perceptual=aligned,
        settings=Settings(),
    )
    assert fusion.match_supported is True
    assert fusion.classification == "VERIFIED_NEAR_DUPLICATE"
    assert fusion.evidence_index > 0.80


def test_high_global_similarity_without_geometry_never_becomes_a_match():
    fusion = fuse_copy_evidence(
        exact_sha256=False,
        ai_similarity=0.93,
        phash_similarity=0.94,
        geometry={"validated": False},
        aligned_perceptual={"available": False, "structure_consensus": None},
        settings=Settings(),
    )
    assert fusion.match_supported is False
    assert fusion.review_supported is True
    assert fusion.classification == "REVIEW_CANDIDATE"
