from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from PIL import Image

from app.domain.enums import AnchorStatus, ProvenanceStatus


@dataclass(frozen=True, slots=True)
class Fingerprints:
    sha256: str
    phash: str


@dataclass(frozen=True, slots=True)
class GeometryEvidence:
    keypoints_query: int
    keypoints_reference: int
    tentative_matches: int
    inliers: int
    inlier_ratio: float
    query_coverage: float
    reprojection_error: float | None
    homography_found: bool
    validated: bool = False
    rejection_reasons: tuple[str, ...] = ()
    reference_coverage: float = 0.0
    symmetric_reprojection_error: float | None = None
    query_grid_cells: int = 0
    reference_grid_cells: int = 0
    query_size: tuple[int, int] = (0, 0)
    reference_size: tuple[int, int] = (0, 0)
    correspondences: tuple[dict, ...] = ()
    regions: tuple[dict, ...] = ()
    homography_query_to_reference: tuple[tuple[float, ...], ...] | None = None


@dataclass(frozen=True, slots=True)
class AlignedPerceptualEvidence:
    """Photometric/structural agreement measured only after validated alignment.

    All values are descriptive evidence in [0, 1], not calibrated probabilities.
    The verifier deliberately refuses to compare unaligned pixels.
    """

    available: bool
    overlap_ratio: float = 0.0
    luminance_correlation: float | None = None
    gradient_correlation: float | None = None
    gradient_magnitude_similarity: float | None = None
    structural_similarity: float | None = None
    color_similarity: float | None = None
    structure_consensus: float | None = None
    evaluation_mask_policy: str = "FULL_VALIDATED_ALIGNMENT_V1"
    support_region_count: int = 0
    support_overlap_ratio: float = 0.0
    support_fraction_of_aligned_overlap: float = 1.0
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceEvidence:
    status: ProvenanceStatus
    provider: str
    reason_codes: list[str]
    manifest_summary: dict | None = None
    trust_details: dict | None = None


@dataclass(frozen=True, slots=True)
class ProofReceipt:
    status: AnchorStatus
    provider: str
    receipt: dict | None = None


@dataclass(frozen=True, slots=True)
class SyntheticDetectorScore:
    provider: str
    score: float
    calibrated: bool
    model_version: str | None = None
    source_scope: str = "UNKNOWN_GENERATORS"
    evidence_family: str = "UNSPECIFIED"
    evidence_family_verified: bool = False
    artifact_sha256: str | None = None
    preprocessing_identity: str | None = None
    score_semantics: str = "RAW_DETECTOR_SCORE_NOT_PROBABILITY"
    warnings: tuple[str, ...] = ()
    # Provider-supplied, deliberately allowlisted diagnostics. These are useful for
    # review (for example Sightengine's generator-category scores), but never become
    # provenance, a legal conclusion, or an explanation invented by CreatorProof.
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class VisibleMarkerEvidence:
    provider: str
    available: bool
    checked: bool
    classification: str
    supports_ai_origin_review: bool
    marker_strength: float | None = None
    markers: tuple[dict, ...] = ()
    reason_codes: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


class FingerprintProvider(Protocol):
    name: str

    def compute(self, raw: bytes, image: Image.Image) -> Fingerprints: ...


class GeometricVerifier(Protocol):
    name: str

    def verify(self, query: Image.Image, reference: Image.Image) -> GeometryEvidence: ...


class AlignedPerceptualVerifierProtocol(Protocol):
    name: str

    def verify(
        self,
        query: Image.Image,
        reference: Image.Image,
        homography_query_to_reference: tuple[tuple[float, ...], ...] | None,
        support_regions: tuple[dict, ...] | list[dict] | None = None,
    ) -> AlignedPerceptualEvidence: ...


class ProvenanceProvider(Protocol):
    name: str

    def inspect(self, source_path: Path) -> ProvenanceEvidence: ...


class ProofAnchor(Protocol):
    name: str

    def anchor(self, packet_hash: str) -> ProofReceipt: ...


class SyntheticDetector(Protocol):
    name: str
    available: bool
    unavailable_reason: str | None

    def predict(self, image: Image.Image) -> SyntheticDetectorScore: ...
