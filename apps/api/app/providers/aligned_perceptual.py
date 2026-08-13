import math

import cv2
import numpy as np
from PIL import Image

from app.providers.contracts import AlignedPerceptualEvidence


class AlignedPerceptualVerifier:
    """Alignment-conditioned full-reference verifier.

    Geometry answers *where* corresponding structure exists. This verifier then asks
    whether the aligned pixels preserve luminance structure and gradients despite
    colour, compression, resize, and mild rendering changes. It never attempts a
    comparison unless the caller supplies a geometry transform that already passed
    the independent robust-verification gates.

    The SSIM-style and gradient-similarity equations are implemented directly here;
    no third-party metric source code is vendored into CreatorProof.
    """

    name = "aligned-structure-ncc-gms-ssim-v1"

    def __init__(self, min_overlap: float = 0.08) -> None:
        self.min_overlap = min_overlap

    @staticmethod
    def _rgb(image: Image.Image) -> np.ndarray:
        return np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0

    @staticmethod
    def _luminance(rgb: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)

    @staticmethod
    def _masked_correlation(left: np.ndarray, right: np.ndarray, mask: np.ndarray) -> float | None:
        a = left[mask].astype(np.float64)
        b = right[mask].astype(np.float64)
        if a.size < 64:
            return None
        a -= float(a.mean())
        b -= float(b.mean())
        denominator = math.sqrt(float(np.dot(a, a)) * float(np.dot(b, b)))
        if denominator <= 1e-12:
            # Constant fields carry no correlation information. Treat two essentially
            # identical constants as agreement; otherwise leave the signal unavailable.
            raw_left = left[mask]
            raw_right = right[mask]
            if float(np.mean(np.abs(raw_left - raw_right))) <= 0.01:
                return 1.0
            return None
        correlation = float(np.dot(a, b) / denominator)
        return max(0.0, min(1.0, (correlation + 1.0) / 2.0))

    @staticmethod
    def _gradient_magnitude(gray: np.ndarray) -> np.ndarray:
        softened = cv2.GaussianBlur(gray, (3, 3), 0.7)
        gx = cv2.Sobel(softened, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(softened, cv2.CV_32F, 0, 1, ksize=3)
        return cv2.magnitude(gx, gy)

    @staticmethod
    def _masked_ssim(left: np.ndarray, right: np.ndarray, mask: np.ndarray) -> float | None:
        if int(mask.sum()) < 64:
            return None
        # Standard local luminance/contrast/structure form on normalized [0,1]
        # luminance. Mask erosion prevents invalid warp borders leaking through the
        # Gaussian support window.
        c1 = 0.01**2
        c2 = 0.03**2
        mu_left = cv2.GaussianBlur(left, (11, 11), 1.5)
        mu_right = cv2.GaussianBlur(right, (11, 11), 1.5)
        left_sq = mu_left * mu_left
        right_sq = mu_right * mu_right
        cross = mu_left * mu_right
        var_left = cv2.GaussianBlur(left * left, (11, 11), 1.5) - left_sq
        var_right = cv2.GaussianBlur(right * right, (11, 11), 1.5) - right_sq
        covariance = cv2.GaussianBlur(left * right, (11, 11), 1.5) - cross
        numerator = (2.0 * cross + c1) * (2.0 * covariance + c2)
        denominator = (left_sq + right_sq + c1) * (var_left + var_right + c2)
        score_map = numerator / np.maximum(denominator, 1e-12)
        kernel = np.ones((7, 7), dtype=np.uint8)
        safe_mask = cv2.erode(mask.astype(np.uint8), kernel, iterations=1).astype(bool)
        if int(safe_mask.sum()) < 64:
            safe_mask = mask
        value = float(np.mean(score_map[safe_mask]))
        return max(0.0, min(1.0, (value + 1.0) / 2.0))

    @staticmethod
    def _color_similarity(left: np.ndarray, right: np.ndarray, mask: np.ndarray) -> float:
        # Deliberately descriptive rather than decisive: colour edits are expected in
        # AI retouching, filters, and recompression. Compare robust per-channel means.
        left_values = left[mask]
        right_values = right[mask]
        left_mean = np.median(left_values, axis=0)
        right_mean = np.median(right_values, axis=0)
        distance = float(np.linalg.norm(left_mean - right_mean) / math.sqrt(3.0))
        return max(0.0, min(1.0, 1.0 - distance))

    @staticmethod
    def _consensus(values: list[float | None]) -> float | None:
        usable = [max(1e-6, min(float(value), 1.0)) for value in values if value is not None]
        if not usable:
            return None
        # Geometric mean is intentionally conservative: one weak structural signal
        # cannot be hidden by a single excellent one.
        return float(math.exp(sum(math.log(value) for value in usable) / len(usable)))

    def verify(
        self,
        query: Image.Image,
        reference: Image.Image,
        homography_query_to_reference: tuple[tuple[float, ...], ...] | None,
    ) -> AlignedPerceptualEvidence:
        if homography_query_to_reference is None:
            return AlignedPerceptualEvidence(available=False, reason="NO_VALIDATED_ALIGNMENT")

        homography = np.asarray(homography_query_to_reference, dtype=np.float64)
        if homography.shape != (3, 3) or not np.isfinite(homography).all():
            return AlignedPerceptualEvidence(available=False, reason="INVALID_ALIGNMENT_MATRIX")

        query_rgb = self._rgb(query)
        reference_rgb = self._rgb(reference)
        reference_height, reference_width = reference_rgb.shape[:2]
        warped_query = cv2.warpPerspective(
            query_rgb,
            homography,
            (reference_width, reference_height),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        query_mask = np.ones(query_rgb.shape[:2], dtype=np.uint8)
        warped_mask = cv2.warpPerspective(
            query_mask,
            homography,
            (reference_width, reference_height),
            flags=cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        ).astype(bool)
        overlap_ratio = float(warped_mask.mean())
        if overlap_ratio < self.min_overlap:
            return AlignedPerceptualEvidence(
                available=False,
                overlap_ratio=round(overlap_ratio, 6),
                reason="INSUFFICIENT_ALIGNED_OVERLAP",
            )

        query_luma = self._luminance(warped_query)
        reference_luma = self._luminance(reference_rgb)
        luminance_correlation = self._masked_correlation(query_luma, reference_luma, warped_mask)

        query_gradient = self._gradient_magnitude(query_luma)
        reference_gradient = self._gradient_magnitude(reference_luma)
        gradient_correlation = self._masked_correlation(
            query_gradient, reference_gradient, warped_mask
        )
        # A normalized gradient-magnitude similarity map. The small stabilizer is in
        # [0,1] luminance-gradient units; the mean communicates preserved edge energy.
        stabilizer = 0.0025
        gms_map = (2.0 * query_gradient * reference_gradient + stabilizer) / (
            query_gradient * query_gradient + reference_gradient * reference_gradient + stabilizer
        )
        gradient_magnitude_similarity = float(np.mean(gms_map[warped_mask]))
        gradient_magnitude_similarity = max(0.0, min(1.0, gradient_magnitude_similarity))
        structural_similarity = self._masked_ssim(query_luma, reference_luma, warped_mask)
        color_similarity = self._color_similarity(warped_query, reference_rgb, warped_mask)
        structure_consensus = self._consensus(
            [
                luminance_correlation,
                gradient_correlation,
                gradient_magnitude_similarity,
                structural_similarity,
            ]
        )

        def rounded(value: float | None) -> float | None:
            return round(value, 6) if value is not None else None

        return AlignedPerceptualEvidence(
            available=True,
            overlap_ratio=round(overlap_ratio, 6),
            luminance_correlation=rounded(luminance_correlation),
            gradient_correlation=rounded(gradient_correlation),
            gradient_magnitude_similarity=rounded(gradient_magnitude_similarity),
            structural_similarity=rounded(structural_similarity),
            color_similarity=rounded(color_similarity),
            structure_consensus=rounded(structure_consensus),
        )
