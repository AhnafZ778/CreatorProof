import math

import cv2
import numpy as np
from PIL import Image

from app.providers.contracts import GeometryEvidence


class ORBGeometricVerifier:
    """Fail-closed CPU geometry verifier with SIFT primary and ORB fallback.

    A fitted homography is never
    treated as a verified match by itself: mutual descriptor matching, redundant support,
    spatial dispersion, two-sided coverage, symmetric transfer error, and matrix sanity
    all have to pass before any correspondence is exposed to the visualization layer.

    The defaults are conservative prototype gates, not universal calibrated thresholds.
    They must be benchmarked on CreatorProof's held-out positive and hard-negative sets.
    """

    name = "sift-orb-usac-magsac-validated-v3"

    def __init__(
        self,
        max_features: int = 2400,
        visualization_limit: int = 64,
        ratio_threshold: float = 0.72,
        min_mutual_matches: int = 10,
        min_inliers: int = 12,
        min_inlier_ratio: float = 0.35,
        min_coverage: float = 0.035,
        min_grid_cells: int = 3,
        max_symmetric_error_normalized: float = 0.0125,
    ) -> None:
        self.max_features = max_features
        self.visualization_limit = visualization_limit
        self.ratio_threshold = ratio_threshold
        self.min_mutual_matches = min_mutual_matches
        self.min_inliers = min_inliers
        self.min_inlier_ratio = min_inlier_ratio
        self.min_coverage = min_coverage
        self.min_grid_cells = min_grid_cells
        self.max_symmetric_error_normalized = max_symmetric_error_normalized

    @staticmethod
    def _gray(image: Image.Image) -> np.ndarray:
        rgb = np.asarray(image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

    @staticmethod
    def _point(point: np.ndarray, width: int, height: int) -> list[float]:
        x = float(point[0]) / max(width - 1, 1)
        y = float(point[1]) / max(height - 1, 1)
        return [round(min(max(x, 0.0), 1.0), 6), round(min(max(y, 0.0), 1.0), 6)]

    @staticmethod
    def _coverage(points: np.ndarray, width: int, height: int) -> float:
        if len(points) < 3:
            return 0.0
        hull = cv2.convexHull(points.astype(np.float32))
        area = float(cv2.contourArea(hull))
        return min(max(area / float(max(width * height, 1)), 0.0), 1.0)

    @staticmethod
    def _grid_cells(points: np.ndarray, width: int, height: int, grid: int = 4) -> int:
        occupied: set[tuple[int, int]] = set()
        for x, y in points:
            gx = min(max(int(float(x) / max(width, 1) * grid), 0), grid - 1)
            gy = min(max(int(float(y) / max(height, 1) * grid), 0), grid - 1)
            occupied.add((gx, gy))
        return len(occupied)

    @staticmethod
    def _box_polygon(
        points: np.ndarray,
        width: int,
        height: int,
        *,
        padding: float = 0.025,
        minimum_span: float = 0.07,
    ) -> list[list[float]]:
        """Return a clean normalized support envelope, never a semantic segmentation mask."""
        if len(points) == 0:
            return []
        normalized = np.column_stack(
            (
                points[:, 0] / max(width - 1, 1),
                points[:, 1] / max(height - 1, 1),
            )
        )
        left, top = np.min(normalized, axis=0)
        right, bottom = np.max(normalized, axis=0)
        center_x = float((left + right) / 2.0)
        center_y = float((top + bottom) / 2.0)
        half_width = max(float(right - left) / 2.0 + padding, minimum_span / 2.0)
        half_height = max(float(bottom - top) / 2.0 + padding, minimum_span / 2.0)
        left = max(0.0, center_x - half_width)
        right = min(1.0, center_x + half_width)
        top = max(0.0, center_y - half_height)
        bottom = min(1.0, center_y + half_height)
        return [
            [round(left, 6), round(top, 6)],
            [round(right, 6), round(top, 6)],
            [round(right, 6), round(bottom, 6)],
            [round(left, 6), round(bottom, 6)],
        ]

    def _support_regions(
        self,
        inlier_rows: list[tuple],
        query: Image.Image,
        reference: Image.Image,
        *,
        grid: int = 4,
        max_regions: int = 4,
    ) -> tuple[tuple[dict, ...], dict[tuple[int, int], str]]:
        """Create small evidence patches from dense local support instead of one global hull.

        Bucketing in query-image space keeps distant matches from being joined by a visually
        misleading convex hull. Corresponding reference boxes are built from the paired inliers.
        These rectangles communicate where verified point support exists; they deliberately do not
        claim to be object boundaries or semantic masks.
        """
        buckets: dict[tuple[int, int], list[tuple]] = {}
        for row in inlier_rows:
            _, query_point, _, _ = row
            gx = min(max(int(float(query_point[0]) / max(query.width, 1) * grid), 0), grid - 1)
            gy = min(max(int(float(query_point[1]) / max(query.height, 1) * grid), 0), grid - 1)
            buckets.setdefault((gx, gy), []).append(row)

        minimum_support = max(3, min(6, math.ceil(len(inlier_rows) * 0.06)))
        candidates = [
            (cell, rows) for cell, rows in buckets.items() if len(rows) >= minimum_support
        ]
        candidates.sort(
            key=lambda item: (
                -len(item[1]),
                float(np.median([row[3] for row in item[1]])),
                item[0][1],
                item[0][0],
            )
        )

        if not candidates and len(inlier_rows) >= self.min_inliers:
            candidates = [((-1, -1), inlier_rows)]

        regions: list[dict] = []
        assignments: dict[tuple[int, int], str] = {}
        for index, (_, rows) in enumerate(candidates[:max_regions]):
            region_id = f"region-verified-patch-{index + 1:03d}"
            query_points = np.float32([row[1] for row in rows]).reshape(-1, 2)
            reference_points = np.float32([row[2] for row in rows]).reshape(-1, 2)
            query_polygon = self._box_polygon(query_points, query.width, query.height)
            reference_polygon = self._box_polygon(
                reference_points, reference.width, reference.height
            )
            if not query_polygon or not reference_polygon:
                continue
            query_width = query_polygon[1][0] - query_polygon[0][0]
            query_height = query_polygon[2][1] - query_polygon[1][1]
            reference_width = reference_polygon[1][0] - reference_polygon[0][0]
            reference_height = reference_polygon[2][1] - reference_polygon[1][1]
            median_error = float(np.median([row[3] for row in rows]))
            regions.append(
                {
                    "id": region_id,
                    "kind": "VERIFIED_SUPPORT_PATCH",
                    "label": f"Verified support patch {index + 1}",
                    "query_polygon": query_polygon,
                    "reference_polygon": reference_polygon,
                    "supporting_inliers": len(rows),
                    "support_fraction": round(len(rows) / max(len(inlier_rows), 1), 6),
                    "query_coverage": round(query_width * query_height, 6),
                    "reference_coverage": round(reference_width * reference_height, 6),
                    "reprojection_error_px": round(median_error, 6),
                    "semantics": "MATCH_SUPPORT_ENVELOPE_NOT_SEGMENTATION",
                }
            )
            for match, _, _, _ in rows:
                assignments[(match.queryIdx, match.trainIdx)] = region_id
        return tuple(regions), assignments

    @staticmethod
    def _matrix(homography: np.ndarray) -> tuple[tuple[float, ...], ...]:
        normalized = homography.astype(np.float64)
        if abs(float(normalized[2, 2])) > 1e-12:
            normalized = normalized / float(normalized[2, 2])
        return tuple(tuple(round(float(value), 10) for value in row) for row in normalized)

    @staticmethod
    def _ratio_matches(
        desc_a: np.ndarray,
        desc_b: np.ndarray,
        threshold: float,
        norm_type: int,
    ):
        matcher = cv2.BFMatcher(norm_type, crossCheck=False)
        pairs = matcher.knnMatch(desc_a, desc_b, k=2)
        return [
            m
            for pair in pairs
            if len(pair) == 2
            for m, n in [pair]
            if m.distance < threshold * n.distance
        ]

    def _empty(
        self,
        query: Image.Image,
        reference: Image.Image,
        *,
        keypoints_query: int,
        keypoints_reference: int,
        tentative_matches: int = 0,
        reasons: tuple[str, ...] = (),
    ) -> GeometryEvidence:
        return GeometryEvidence(
            keypoints_query=keypoints_query,
            keypoints_reference=keypoints_reference,
            tentative_matches=tentative_matches,
            inliers=0,
            inlier_ratio=0.0,
            query_coverage=0.0,
            reprojection_error=None,
            homography_found=False,
            validated=False,
            rejection_reasons=reasons,
            query_size=query.size,
            reference_size=reference.size,
        )

    def verify(self, query: Image.Image, reference: Image.Image) -> GeometryEvidence:
        q = self._gray(query)
        r = self._gray(reference)
        if hasattr(cv2, "SIFT_create"):
            detector = cv2.SIFT_create(nfeatures=self.max_features)
            norm_type = cv2.NORM_L2
            ratio_threshold = max(self.ratio_threshold, 0.75)
            evidence_type = "SIFT_USAC_MAGSAC_VERIFIED_INLIER"
        else:
            detector = cv2.ORB_create(nfeatures=self.max_features)
            norm_type = cv2.NORM_HAMMING
            ratio_threshold = self.ratio_threshold
            evidence_type = "ORB_USAC_MAGSAC_VERIFIED_INLIER"
        q_kp, q_desc = detector.detectAndCompute(q, None)
        r_kp, r_desc = detector.detectAndCompute(r, None)
        q_count = len(q_kp or [])
        r_count = len(r_kp or [])

        if q_desc is None or r_desc is None or q_count < 4 or r_count < 4:
            return self._empty(
                query,
                reference,
                keypoints_query=q_count,
                keypoints_reference=r_count,
                reasons=("INSUFFICIENT_KEYPOINTS",),
            )

        forward = self._ratio_matches(q_desc, r_desc, ratio_threshold, norm_type)
        reverse = self._ratio_matches(r_desc, q_desc, ratio_threshold, norm_type)
        reverse_pairs = {(match.trainIdx, match.queryIdx) for match in reverse}
        mutual = [match for match in forward if (match.queryIdx, match.trainIdx) in reverse_pairs]
        mutual.sort(key=lambda match: (match.distance, match.queryIdx, match.trainIdx))

        if len(mutual) < self.min_mutual_matches:
            return self._empty(
                query,
                reference,
                keypoints_query=q_count,
                keypoints_reference=r_count,
                tentative_matches=len(mutual),
                reasons=("INSUFFICIENT_MUTUAL_MATCHES",),
            )

        q_pts = np.float32([q_kp[m.queryIdx].pt for m in mutual]).reshape(-1, 1, 2)
        r_pts = np.float32([r_kp[m.trainIdx].pt for m in mutual]).reshape(-1, 1, 2)
        method = getattr(cv2, "USAC_MAGSAC", cv2.RANSAC)
        homography, mask = cv2.findHomography(q_pts, r_pts, method, 4.0)
        if homography is None or mask is None or not np.isfinite(homography).all():
            return self._empty(
                query,
                reference,
                keypoints_query=q_count,
                keypoints_reference=r_count,
                tentative_matches=len(mutual),
                reasons=("HOMOGRAPHY_NOT_FOUND",),
            )

        inlier_mask = mask.ravel().astype(bool)
        inliers = int(inlier_mask.sum())
        inlier_ratio = inliers / max(len(mutual), 1)
        q_xy = q_pts.reshape(-1, 2)
        r_xy = r_pts.reshape(-1, 2)
        inlier_q = q_xy[inlier_mask]
        inlier_r = r_xy[inlier_mask]
        query_coverage = self._coverage(inlier_q, query.width, query.height)
        reference_coverage = self._coverage(inlier_r, reference.width, reference.height)
        query_grid_cells = self._grid_cells(inlier_q, query.width, query.height)
        reference_grid_cells = self._grid_cells(inlier_r, reference.width, reference.height)

        projected = cv2.perspectiveTransform(inlier_q.reshape(-1, 1, 2), homography).reshape(-1, 2)
        forward_errors = np.linalg.norm(projected - inlier_r, axis=1) if inliers else np.array([])
        reprojection_error = float(forward_errors.mean()) if len(forward_errors) else None

        rejection_reasons: list[str] = []
        inverse: np.ndarray | None = None
        try:
            inverse = np.linalg.inv(homography)
        except np.linalg.LinAlgError:
            rejection_reasons.append("HOMOGRAPHY_SINGULAR")

        symmetric_error: float | None = None
        if inverse is not None and inliers:
            back_projected = cv2.perspectiveTransform(inlier_r.reshape(-1, 1, 2), inverse).reshape(
                -1, 2
            )
            backward_errors = np.linalg.norm(back_projected - inlier_q, axis=1)
            q_diagonal = max(math.hypot(query.width, query.height), 1.0)
            r_diagonal = max(math.hypot(reference.width, reference.height), 1.0)
            symmetric_error = 0.5 * (
                float(np.median(forward_errors)) / r_diagonal
                + float(np.median(backward_errors)) / q_diagonal
            )

        normalized_h = (
            homography / homography[2, 2] if abs(homography[2, 2]) > 1e-12 else homography
        )
        determinant = float(np.linalg.det(normalized_h))
        condition = float(np.linalg.cond(normalized_h))

        if inliers < self.min_inliers:
            rejection_reasons.append("INSUFFICIENT_INLIERS")
        if inlier_ratio < self.min_inlier_ratio:
            rejection_reasons.append("LOW_INLIER_RATIO")
        if query_coverage < self.min_coverage:
            rejection_reasons.append("LOW_QUERY_COVERAGE")
        if reference_coverage < self.min_coverage:
            rejection_reasons.append("LOW_REFERENCE_COVERAGE")
        if query_grid_cells < self.min_grid_cells:
            rejection_reasons.append("POOR_QUERY_SPATIAL_DISPERSION")
        if reference_grid_cells < self.min_grid_cells:
            rejection_reasons.append("POOR_REFERENCE_SPATIAL_DISPERSION")
        if symmetric_error is None or symmetric_error > self.max_symmetric_error_normalized:
            rejection_reasons.append("HIGH_SYMMETRIC_TRANSFER_ERROR")
        if not math.isfinite(determinant) or abs(determinant) < 1e-8:
            rejection_reasons.append("DEGENERATE_HOMOGRAPHY")
        if not math.isfinite(condition) or condition > 1e8:
            rejection_reasons.append("UNSTABLE_HOMOGRAPHY")

        validated = not rejection_reasons
        correspondences: tuple[dict, ...] = ()
        regions: tuple[dict, ...] = ()
        visible_homography = None

        if validated:
            inlier_rows: list[tuple] = []
            error_index = 0
            for match, q_point, r_point, keep in zip(mutual, q_xy, r_xy, inlier_mask, strict=True):
                if not keep:
                    continue
                inlier_rows.append((match, q_point, r_point, float(forward_errors[error_index])))
                error_index += 1
            regions, region_assignments = self._support_regions(inlier_rows, query, reference)
            inlier_rows.sort(
                key=lambda row: (
                    row[3],
                    row[0].distance,
                    row[0].queryIdx,
                    row[0].trainIdx,
                )
            )
            displayed = inlier_rows[: self.visualization_limit]
            correspondences = tuple(
                {
                    "id": f"corr-{index + 1:03d}",
                    "query": self._point(q_point, query.width, query.height),
                    "reference": self._point(r_point, reference.width, reference.height),
                    "descriptor_distance": round(float(match.distance), 3),
                    "transfer_error_px": round(float(transfer_error), 4),
                    "region_id": region_assignments.get((match.queryIdx, match.trainIdx)),
                    "evidence_type": evidence_type,
                }
                for index, (match, q_point, r_point, transfer_error) in enumerate(displayed)
            )
            visible_homography = self._matrix(homography)

        return GeometryEvidence(
            keypoints_query=q_count,
            keypoints_reference=r_count,
            tentative_matches=len(mutual),
            inliers=inliers,
            inlier_ratio=round(inlier_ratio, 6),
            query_coverage=round(query_coverage, 6),
            reference_coverage=round(reference_coverage, 6),
            reprojection_error=round(reprojection_error, 6)
            if reprojection_error is not None
            else None,
            symmetric_reprojection_error=round(symmetric_error, 8)
            if symmetric_error is not None
            else None,
            homography_found=True,
            validated=validated,
            rejection_reasons=tuple(dict.fromkeys(rejection_reasons)),
            query_grid_cells=query_grid_cells,
            reference_grid_cells=reference_grid_cells,
            query_size=query.size,
            reference_size=reference.size,
            correspondences=correspondences,
            regions=regions,
            homography_query_to_reference=visible_homography,
        )
