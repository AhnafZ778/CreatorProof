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


def test_verified_support_mask_recovers_partial_copy_from_unrelated_background():
    reference = _structured_image()
    reference_array = np.asarray(reference, dtype=np.uint8)
    rng = np.random.default_rng(778)
    query_array = rng.integers(0, 256, size=reference_array.shape, dtype=np.uint8)
    left, top, right, bottom = 52, 48, 274, 184
    query_array[top:bottom, left:right] = reference_array[top:bottom, left:right]
    query = Image.fromarray(query_array)
    identity = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )

    verifier = AlignedPerceptualVerifier()
    full = asdict(verifier.verify(query, reference, identity))
    regional = asdict(
        verifier.verify(
            query,
            reference,
            identity,
            [
                {
                    "kind": "VERIFIED_SUPPORT_PATCH",
                    "reference_polygon": [
                        [left / (reference.width - 1), top / (reference.height - 1)],
                        [right / (reference.width - 1), top / (reference.height - 1)],
                        [right / (reference.width - 1), bottom / (reference.height - 1)],
                        [left / (reference.width - 1), bottom / (reference.height - 1)],
                    ],
                }
            ],
        )
    )

    assert full["available"] is True
    assert regional["available"] is True
    assert regional["evaluation_mask_policy"] == "GEOMETRY_VERIFIED_SUPPORT_REGIONS_V1"
    assert regional["support_region_count"] == 1
    assert regional["support_fraction_of_aligned_overlap"] < 0.20
    assert regional["structure_consensus"] > 0.95
    assert regional["structure_consensus"] > full["structure_consensus"] + 0.20


def _flat_repetitive_image() -> Image.Image:
    """Flat vector-style art: no texture, and every element identical.

    This is the shape of work the ratio test cannot handle, because each motif
    has an equally good twin and every match is discarded as ambiguous.
    """
    image = Image.new("RGB", (620, 620), "#1d3461")
    draw = ImageDraw.Draw(image)
    for index in range(16):
        x = 40 + index * 33
        y = 40 + index * 30
        draw.ellipse((x, y, x + 120, y + 120), outline="#e0a13a", width=6)
    return image


def _verified(query: Image.Image, reference: Image.Image, *, escalate: bool) -> tuple[dict, dict]:
    geometry = asdict(
        ORBGeometricVerifier().verify(query, reference, escalate=escalate)
    )
    alignment = (
        geometry["homography_query_to_reference"]
        if geometry["alignment_grade"] in {"STRICT", "CORROBORATION_REQUIRED"}
        else None
    )
    aligned = asdict(
        AlignedPerceptualVerifier().verify(
            query,
            reference,
            alignment,
            geometry["regions"] if alignment is not None else None,
        )
    )
    return geometry, aligned


def test_a_mirrored_repost_is_matched_and_reported_as_a_mirror():
    reference = _structured_image()
    query = reference.transpose(Image.FLIP_LEFT_RIGHT)

    unescalated, _ = _verified(query, reference, escalate=False)
    assert unescalated["validated"] is False, "a mirror should defeat plain descriptor matching"

    geometry, aligned = _verified(query, reference, escalate=True)
    assert geometry["validated"] is True
    assert geometry["reflected"] is True
    assert geometry["alignment_grade"] == "STRICT"

    fusion = fuse_copy_evidence(
        exact_sha256=False,
        ai_similarity=0.95,
        phash_similarity=0.5,
        geometry=geometry,
        aligned_perceptual=aligned,
        settings=Settings(),
    )
    assert fusion.match_supported is True
    assert "ALIGNMENT_IS_A_MIRROR_IMAGE" in fusion.reason_codes


def test_a_mirrored_alignment_maps_back_onto_the_file_as_submitted():
    """The mirror must not leak: the warp has to fit the unflipped query."""
    reference = _structured_image()
    query = reference.transpose(Image.FLIP_LEFT_RIGHT)
    geometry, aligned = _verified(query, reference, escalate=True)

    assert aligned["available"] is True
    assert aligned["overlap_ratio"] > 0.98
    assert aligned["structure_consensus"] > 0.98
    for correspondence in geometry["correspondences"]:
        x, y = correspondence["query"]
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def test_flat_repetitive_art_is_recovered_only_when_aligned_pixels_agree():
    reference = _flat_repetitive_image()
    query = reference.resize((310, 310), Image.LANCZOS).rotate(
        5, expand=True, resample=Image.BICUBIC
    )

    unescalated, _ = _verified(query, reference, escalate=False)
    assert unescalated["validated"] is False, "the ratio test should starve on repeated motifs"

    geometry, aligned = _verified(query, reference, escalate=True)
    assert geometry["alignment_grade"] == "CORROBORATION_REQUIRED"
    assert geometry["validated"] is False, "relaxed matching must never validate by itself"

    fusion = fuse_copy_evidence(
        exact_sha256=False,
        ai_similarity=0.90,
        phash_similarity=0.5,
        geometry=geometry,
        aligned_perceptual=aligned,
        settings=Settings(),
    )
    assert fusion.match_supported is True
    assert "RELAXED_ALIGNMENT_CONFIRMED_BY_ALIGNED_PIXELS" in fusion.reason_codes


def test_a_relaxed_alignment_whose_pixels_disagree_is_not_a_match():
    fusion = fuse_copy_evidence(
        exact_sha256=False,
        ai_similarity=0.90,
        phash_similarity=0.70,
        geometry={"validated": False, "alignment_grade": "CORROBORATION_REQUIRED"},
        aligned_perceptual={"available": True, "structure_consensus": 0.77},
        settings=Settings(),
    )
    assert fusion.match_supported is False
    assert fusion.review_supported is True
    assert "RELAXED_ALIGNMENT_NOT_CONFIRMED_BY_ALIGNED_PIXELS" in fusion.reason_codes


def test_a_small_crop_matches_on_the_alignment_when_the_descriptor_cannot_see_it():
    """A corner of a work is a different picture globally but the same pixels."""
    fusion = fuse_copy_evidence(
        exact_sha256=False,
        ai_similarity=0.36,
        phash_similarity=0.55,
        geometry={
            "validated": True,
            "alignment_grade": "STRICT",
            "inliers": 14,
            "inlier_ratio": 1.0,
            "query_coverage": 0.28,
            "reference_coverage": 0.06,
            "symmetric_reprojection_error": 0.0004,
        },
        aligned_perceptual={"available": True, "structure_consensus": 0.9999},
        settings=Settings(),
    )
    assert fusion.match_supported is True
    assert fusion.classification == "VERIFIED_PARTIAL_COPY_EVIDENCE"
    assert "ALIGNED_PIXELS_EFFECTIVELY_IDENTICAL" in fusion.reason_codes


def test_a_merely_similar_aligned_region_still_needs_a_second_opinion():
    """The conclusive path must not fire on anything short of identical pixels."""
    fusion = fuse_copy_evidence(
        exact_sha256=False,
        ai_similarity=0.36,
        phash_similarity=0.55,
        geometry={
            "validated": True,
            "alignment_grade": "STRICT",
            "inliers": 14,
            "inlier_ratio": 1.0,
            "query_coverage": 0.28,
            "reference_coverage": 0.06,
            "symmetric_reprojection_error": 0.0004,
        },
        aligned_perceptual={"available": True, "structure_consensus": 0.80},
        settings=Settings(),
    )
    assert fusion.match_supported is False
    assert fusion.review_supported is True
