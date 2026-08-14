import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CopyFusionResult:
    evidence_index: float
    evidence_tier: str
    classification: str
    match_supported: bool
    review_supported: bool
    geometry_quality: float
    independent_support_count: int
    signal_states: dict[str, str]
    reason_codes: tuple[str, ...]
    score_semantics: str = "EVIDENCE_INDEX_NOT_PROBABILITY"


def _clamp(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def geometry_quality(geometry: dict) -> float:
    """Summarize validated geometric support without replacing the raw metrics."""
    if not geometry.get("validated"):
        return 0.0
    inliers = _clamp(float(geometry.get("inliers") or 0) / 60.0)
    ratio = _clamp(float(geometry.get("inlier_ratio") or 0.0))
    query_coverage = max(float(geometry.get("query_coverage") or 0.0), 0.0)
    reference_coverage = max(float(geometry.get("reference_coverage") or 0.0), 0.0)
    geometric_coverage = math.sqrt(query_coverage * reference_coverage)
    coverage = _clamp(geometric_coverage / 0.20)
    symmetric_error = geometry.get("symmetric_reprojection_error")
    error_quality = (
        0.5 if symmetric_error is None else _clamp(1.0 - float(symmetric_error) / 0.0125)
    )
    return round(0.25 * inliers + 0.30 * ratio + 0.25 * coverage + 0.20 * error_quality, 6)


def fuse_copy_evidence(
    *,
    exact_sha256: bool,
    ai_similarity: float | None,
    phash_similarity: float,
    geometry: dict,
    aligned_perceptual: dict,
    settings,
) -> CopyFusionResult:
    """Fuse evidence with explicit corroboration gates.

    Retrieval and pHash may nominate a candidate, but neither can produce MATCH_FOUND
    alone. A non-byte-identical match requires robust local geometry and
    alignment-conditioned structural agreement; SSCD and pHash only corroborate it.

    Thresholds are prototype operating points and must be calibrated on deployment-domain
    positives and hard negatives. The returned evidence index is descriptive, never a
    posterior probability or legal-infringement score.
    """
    if exact_sha256:
        return CopyFusionResult(
            evidence_index=1.0,
            evidence_tier="VERY_HIGH",
            classification="EXACT_BINARY_COPY",
            match_supported=True,
            review_supported=False,
            geometry_quality=1.0,
            independent_support_count=4,
            signal_states={
                "sha256": "EXACT",
                "retrieval": "CORROBORATING",
                "phash": "CORROBORATING",
                "geometry": "NOT_REQUIRED_FOR_EXACT_HASH",
                "aligned_structure": "NOT_REQUIRED_FOR_EXACT_HASH",
            },
            reason_codes=("EXACT_SHA256_MATCH",),
        )

    geometry_valid = bool(geometry.get("validated"))
    geometry_score = geometry_quality(geometry)
    structure_value = aligned_perceptual.get("structure_consensus")
    structure = _clamp(float(structure_value)) if structure_value is not None else None
    aligned_available = bool(aligned_perceptual.get("available")) and structure is not None
    ai = _clamp(ai_similarity) if ai_similarity is not None else None
    phash = _clamp(phash_similarity)

    structure_strong = bool(
        aligned_available and structure >= settings.copy_structure_match_similarity
    )
    ai_support = bool(ai is not None and ai >= settings.copy_sscd_support_similarity)
    ai_geometry_match = bool(ai is not None and ai >= settings.copy_geometry_sscd_match_similarity)
    phash_support = phash >= settings.copy_phash_support_similarity

    # Independent-support count is intentionally coarse and auditable. Aligned structure
    # is conditioned on geometry, so it is counted as one verifier family, not several
    # independent votes for its internal NCC/GMS/SSIM components.
    support_count = sum((ai_support, phash_support, structure_strong))

    strong_structural_path = geometry_valid and structure_strong and (ai_support or phash_support)
    exceptionally_structural_path = (
        geometry_valid
        and aligned_available
        and structure is not None
        and structure >= settings.copy_structure_very_strong_similarity
        and geometry_score >= settings.copy_geometry_very_strong_quality
    )
    # Geometry can be spuriously fit on repeated line work, text, borders, or a shared
    # visual tradition. It therefore never produces a copy finding with a global SSCD
    # score alone. Even the very-strong path requires alignment-conditioned structure.
    very_strong_global_path = bool(
        geometry_valid
        and ai is not None
        and ai >= settings.copy_sscd_very_strong_similarity
        and geometry_score >= settings.copy_geometry_very_strong_quality
        and aligned_available
        and structure is not None
        and structure >= settings.copy_structure_support_similarity
    )
    # Flat and repetitive work cannot clear the strict alignment gates: the ratio
    # test throws away every repeated element, so there is nothing left to fit.
    # Where alignment was only recovered under relaxed matching the geometry
    # counts for nothing on its own, and the finding rests entirely on the
    # aligned pixels agreeing to the very-strong standard while the descriptor
    # independently says the same. That keeps a loosely fitted homography from
    # ever being the reason a match is reported.
    corroboration_required = geometry.get("alignment_grade") == "CORROBORATION_REQUIRED"
    corroborated_alignment_path = bool(
        corroboration_required
        and aligned_available
        and structure is not None
        and structure >= settings.copy_structure_very_strong_similarity
        and (ai_support or phash_support)
    )
    # Cropping is where the retrieval requirement above works against the
    # evidence: a corner of a work is a different picture globally, so the
    # descriptor score collapses even though the overlapping pixels are the
    # original. This path stands on the alignment alone, and only when it is
    # strictly verified, nearly every match agrees with it, and the aligned
    # pixels are effectively identical — a state different images do not reach,
    # because reaching it would make them the same image.
    conclusive_alignment_path = bool(
        geometry_valid
        and aligned_available
        and structure is not None
        and structure >= settings.copy_conclusive_structure_similarity
        and float(geometry.get("inlier_ratio") or 0.0) >= settings.copy_conclusive_inlier_ratio
    )
    match_supported = bool(
        strong_structural_path
        or exceptionally_structural_path
        or very_strong_global_path
        or corroborated_alignment_path
        or conclusive_alignment_path
    )

    if match_supported:
        query_coverage = float(geometry.get("query_coverage") or 0.0)
        reference_coverage = float(geometry.get("reference_coverage") or 0.0)
        classification = (
            "VERIFIED_PARTIAL_COPY_EVIDENCE"
            if min(query_coverage, reference_coverage) < 0.18
            else "VERIFIED_NEAR_DUPLICATE"
        )
    else:
        classification = "NEAREST_CANDIDATE_ONLY"

    high_global_without_geometry = bool(
        (ai is not None and ai >= settings.copy_global_review_similarity)
        or phash >= settings.copy_phash_review_similarity
    )
    review_supported = bool(
        not match_supported
        and (geometry_valid or high_global_without_geometry or corroboration_required)
    )
    if review_supported:
        classification = "REVIEW_CANDIDATE"

    # Descriptive evidence index. Geometry and aligned structure dominate because a
    # high global descriptor score alone must not look like a high-confidence match.
    retrieval_component = ai if ai is not None else phash
    structure_component = structure if aligned_available and structure is not None else 0.0
    evidence_index = _clamp(
        0.25 * retrieval_component
        + 0.15 * phash
        + 0.32 * geometry_score
        + 0.28 * structure_component
    )

    if match_supported and evidence_index >= 0.84:
        tier = "VERY_HIGH"
    elif match_supported:
        tier = "HIGH"
    elif review_supported:
        tier = "REVIEW"
    else:
        tier = "LOW"

    reasons: list[str] = []
    if geometry_valid:
        reasons.append("ROBUST_GEOMETRY_VERIFIED")
    if structure_strong:
        reasons.append("ALIGNED_STRUCTURE_CORROBORATES")
    if ai_geometry_match:
        reasons.append(
            "SSCD_GEOMETRY_SUPPORT_REQUIRES_ALIGNED_STRUCTURE"
            if not match_supported
            else "SSCD_GEOMETRY_AND_STRUCTURE_CORROBORATE"
        )
    elif ai_support:
        reasons.append("SSCD_SUPPORTS_CANDIDATE")
    if phash_support:
        reasons.append("PHASH_SUPPORTS_CANDIDATE")
    if conclusive_alignment_path:
        reasons.append("ALIGNED_PIXELS_EFFECTIVELY_IDENTICAL")
    if bool(geometry.get("reflected")):
        reasons.append("ALIGNMENT_IS_A_MIRROR_IMAGE")
    if corroboration_required:
        reasons.append(
            "RELAXED_ALIGNMENT_CONFIRMED_BY_ALIGNED_PIXELS"
            if corroborated_alignment_path
            else "RELAXED_ALIGNMENT_NOT_CONFIRMED_BY_ALIGNED_PIXELS"
        )
    elif not geometry_valid:
        reasons.append("NO_VERIFIED_LOCAL_GEOMETRY")
    if not reasons:
        reasons.append("NO_CORROBORATED_COPY_EVIDENCE")

    signal_states = {
        "sha256": "DIFFERENT_BYTES",
        "retrieval": ("SUPPORT" if ai_support else "WEAK" if ai is not None else "UNAVAILABLE"),
        "phash": "SUPPORT" if phash_support else "WEAK",
        "geometry": (
            "VERIFIED"
            if geometry_valid
            else "RECOVERED_PENDING_PIXEL_AGREEMENT"
            if corroboration_required
            else "REJECTED"
        ),
        "aligned_structure": (
            "STRONG"
            if structure_strong
            else "MEASURED_WEAK"
            if aligned_available
            else "UNAVAILABLE_WITHOUT_GEOMETRY"
        ),
    }
    return CopyFusionResult(
        evidence_index=round(evidence_index, 6),
        evidence_tier=tier,
        classification=classification,
        match_supported=match_supported,
        review_supported=review_supported,
        geometry_quality=geometry_score,
        independent_support_count=support_count,
        signal_states=signal_states,
        reason_codes=tuple(reasons),
    )
