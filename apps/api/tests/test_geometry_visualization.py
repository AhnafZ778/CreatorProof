import numpy as np
from PIL import Image

from app.providers.geometry import ORBGeometricVerifier


def test_geometry_exposes_resize_safe_visual_evidence():
    rng = np.random.default_rng(42)
    pixels = rng.integers(0, 256, size=(240, 320, 3), dtype=np.uint8)
    image = Image.fromarray(pixels)

    evidence = ORBGeometricVerifier(visualization_limit=24).verify(image, image.copy())

    assert evidence.homography_found is True
    assert evidence.validated is True
    assert evidence.rejection_reasons == ()
    assert evidence.query_size == (320, 240)
    assert evidence.reference_size == (320, 240)
    assert 1 <= len(evidence.correspondences) <= 24
    assert evidence.regions
    assert evidence.homography_query_to_reference is not None
    assert all(region["kind"] == "VERIFIED_SUPPORT_PATCH" for region in evidence.regions)
    assert all(len(region["query_polygon"]) == 4 for region in evidence.regions)
    assert all(len(region["reference_polygon"]) == 4 for region in evidence.regions)
    assert all(
        region["semantics"] == "MATCH_SUPPORT_ENVELOPE_NOT_SEGMENTATION"
        for region in evidence.regions
    )

    for correspondence in evidence.correspondences:
        assert correspondence["transfer_error_px"] >= 0.0
        for point in (correspondence["query"], correspondence["reference"]):
            assert 0.0 <= point[0] <= 1.0
            assert 0.0 <= point[1] <= 1.0


def test_unrelated_images_fail_closed_without_annotations():
    left_rng = np.random.default_rng(123)
    right_rng = np.random.default_rng(987)
    left = Image.fromarray(left_rng.integers(0, 256, size=(300, 400, 3), dtype=np.uint8))
    right = Image.fromarray(right_rng.integers(0, 256, size=(300, 400, 3), dtype=np.uint8))

    evidence = ORBGeometricVerifier().verify(left, right)

    assert evidence.validated is False
    assert evidence.rejection_reasons
    assert evidence.correspondences == ()
    assert evidence.regions == ()
    assert evidence.homography_query_to_reference is None
