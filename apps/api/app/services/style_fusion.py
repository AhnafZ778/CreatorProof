from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def _unit(value: float | None) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float(np.clip(value, 0.0, 1.0))


def style_mechanics(factors: dict[str, float] | None) -> float | None:
    if not factors:
        return None
    required = ("palette", "tone", "stroke_orientation", "texture")
    if any(name not in factors for name in required):
        return None
    # Mark-making and texture receive more weight than palette because colour alone is
    # easy to imitate accidentally and frequently follows subject matter.
    value = (
        0.10 * float(factors["palette"])
        + 0.15 * float(factors["tone"])
        + 0.375 * float(factors["stroke_orientation"])
        + 0.375 * float(factors["texture"])
    )
    return _unit(value)


def bidirectional_tile_consistency(tile_map: dict | None) -> float | None:
    if not tile_map:
        return None
    query = [float(item["score"]) for item in tile_map.get("query_cells", [])]
    reference = [float(item["score"]) for item in tile_map.get("reference_cells", [])]
    if not query or not reference:
        return None
    # The median resists one spectacular tile match dominating a whole-image claim.
    return _unit(0.5 * float(np.median(query)) + 0.5 * float(np.median(reference)))


@dataclass(frozen=True, slots=True)
class StyleFusionResult:
    evidence_index: float
    evidence_tier: str
    classification: str
    review_recommended: bool
    independent_support_count: int
    learned_style_similarity: float | None
    mechanics_similarity: float | None
    tile_consistency: float | None
    content_similarity: float | None
    style_content_gap: float | None
    content_separation_support: float | None
    content_confound_state: str
    profile_reliability: str
    calibration_state: str
    negative_tail_p: float | None
    positive_support_percentile: float | None
    false_match_control_supported: bool
    reason_codes: list[str]
    score_semantics: str


def fuse_style_evidence(
    *,
    learned_provider_active: bool,
    raw_style_similarity: float | None,
    factors: dict[str, float] | None,
    tile_map: dict | None,
    content_similarity: float | None,
    sample_count: int,
    discrimination_gap: float | None,
    catalog_margin: float | None,
    calibration: dict | None = None,
    settings,
) -> StyleFusionResult:
    learned = _unit(raw_style_similarity) if learned_provider_active else None
    mechanics = style_mechanics(factors)
    tile = bidirectional_tile_consistency(tile_map)
    content = _unit(content_similarity)
    gap = learned - content if learned is not None and content is not None else None
    separation = _unit((gap + 0.05) / 0.45) if gap is not None else None

    components: list[tuple[float, float]] = []
    if learned is not None:
        components.append((0.50, learned))
    if mechanics is not None:
        components.append((0.25 if learned is not None else 0.65, mechanics))
    if tile is not None:
        components.append((0.15 if learned is not None else 0.35, tile))
    if separation is not None and learned is not None:
        components.append((0.10, separation))
    weight_total = sum(weight for weight, _ in components)
    evidence_index = (
        sum(weight * value for weight, value in components) / weight_total
        if weight_total > 0
        else 0.0
    )

    reason_codes: list[str] = []
    support_count = 0
    if learned is not None and learned >= settings.style_learned_support_similarity:
        support_count += 1
        reason_codes.append("LEARNED_STYLE_EMBEDDING_SUPPORT")
    if mechanics is not None and mechanics >= settings.style_mechanics_support_similarity:
        support_count += 1
        reason_codes.append("MARK_MAKING_AND_TEXTURE_SUPPORT")
    if tile is not None and tile >= settings.style_tile_support_similarity:
        support_count += 1
        reason_codes.append("BIDIRECTIONAL_TILE_STYLE_SUPPORT")
    if gap is not None and gap >= settings.style_content_gap_support:
        support_count += 1
        reason_codes.append("STYLE_EXCEEDS_CONTENT_CONTROL")
    if catalog_margin is not None and catalog_margin >= settings.style_catalog_margin_support:
        support_count += 1
        reason_codes.append("CATALOG_RANKING_MARGIN_SUPPORT")

    if content is None:
        confound_state = "CONTENT_CONTROL_UNAVAILABLE"
    elif gap is not None and gap >= settings.style_content_gap_support:
        confound_state = "STYLE_EXCEEDS_CONTENT_CONTROL"
    elif content >= 0.75 and (gap is None or gap < 0.10):
        confound_state = "STYLE_AND_CONTENT_CONFOUNDED"
        reason_codes.append("CONTENT_CONFOUND_REQUIRES_CAUTION")
    else:
        confound_state = "MIXED_STYLE_AND_CONTENT_SIGNAL"

    if sample_count >= 3:
        profile_reliability = "MULTI_WORK_PROFILE"
    elif sample_count == 2:
        profile_reliability = "LIMITED_PROFILE"
    else:
        profile_reliability = "SINGLE_EXEMPLAR_ONLY"
        reason_codes.append("SINGLE_EXEMPLAR_LIMITATION")

    raw_cosine_interpretable = discrimination_gap is not None and discrimination_gap > 0
    if discrimination_gap is not None and discrimination_gap <= 0:
        reason_codes.append("RAW_COSINE_CATALOG_INVERSION_DETECTED")

    calibration = calibration or {}
    calibration_ready = bool(calibration.get("ready"))
    negative_tail_p = calibration.get("negative_tail_p")
    positive_percentile = calibration.get("positive_support_percentile")
    false_match_control = bool(
        calibration_ready
        and negative_tail_p is not None
        and float(negative_tail_p) <= settings.style_high_max_negative_tail_p
        and positive_percentile is not None
        and float(positive_percentile) >= settings.style_high_min_positive_percentile
    )
    if calibration_ready:
        reason_codes.append("CATALOG_RELATIVE_EMPIRICAL_SUPPORT_READY")
    else:
        reason_codes.extend(calibration.get("reason_codes") or ["STYLE_CALIBRATION_INSUFFICIENT"])

    very_high = (
        learned_provider_active
        and evidence_index >= settings.style_evidence_very_high_similarity
        and support_count >= 3
        and sample_count >= 3
        and raw_cosine_interpretable
        and calibration_ready
        and negative_tail_p is not None
        and float(negative_tail_p) <= settings.style_very_high_max_negative_tail_p
        and positive_percentile is not None
        and float(positive_percentile) >= settings.style_very_high_min_positive_percentile
        and confound_state != "STYLE_AND_CONTENT_CONFOUNDED"
    )
    high = (
        learned_provider_active
        and evidence_index >= settings.style_evidence_high_similarity
        and support_count >= 3
        and sample_count >= 3
        and raw_cosine_interpretable
        and false_match_control
    )
    if not learned_provider_active:
        tier = "DIAGNOSTIC"
        classification = "DIAGNOSTIC_STYLE_RESEMBLANCE_ONLY"
    elif very_high:
        tier = "VERY_HIGH"
        classification = "VERY_HIGH_STYLE_RESEMBLANCE_EVIDENCE"
    elif high:
        tier = "HIGH"
        classification = "HIGH_STYLE_RESEMBLANCE_EVIDENCE"
    elif evidence_index >= settings.style_evidence_review_similarity and support_count >= 1:
        tier = "REVIEW"
        classification = (
            "STYLE_RESEMBLANCE_REVIEW_CANDIDATE"
            if calibration_ready
            else "UNCALIBRATED_STYLE_RESEMBLANCE_REVIEW_CANDIDATE"
        )
    else:
        tier = "LOW"
        classification = "LOW_STYLE_RESEMBLANCE_EVIDENCE"

    review_recommended = learned_provider_active and tier in {"VERY_HIGH", "HIGH", "REVIEW"}
    if review_recommended:
        reason_codes.append("STYLE_RESEMBLANCE_REVIEW_RECOMMENDED")
    if not learned_provider_active:
        reason_codes.append("DIAGNOSTIC_FALLBACK_CANNOT_ATTRIBUTE_CREATOR")

    return StyleFusionResult(
        evidence_index=round(float(evidence_index), 6),
        evidence_tier=tier,
        classification=classification,
        review_recommended=review_recommended,
        independent_support_count=support_count,
        learned_style_similarity=round(learned, 6) if learned is not None else None,
        mechanics_similarity=round(mechanics, 6) if mechanics is not None else None,
        tile_consistency=round(tile, 6) if tile is not None else None,
        content_similarity=round(content, 6) if content is not None else None,
        style_content_gap=round(gap, 6) if gap is not None else None,
        content_separation_support=round(separation, 6) if separation is not None else None,
        content_confound_state=confound_state,
        profile_reliability=profile_reliability,
        calibration_state=str(calibration.get("state") or "NOT_PROVIDED"),
        negative_tail_p=(round(float(negative_tail_p), 6) if negative_tail_p is not None else None),
        positive_support_percentile=(
            round(float(positive_percentile), 6) if positive_percentile is not None else None
        ),
        false_match_control_supported=false_match_control,
        reason_codes=reason_codes,
        score_semantics=(
            "CATALOG_CALIBRATED_STYLE_EVIDENCE_INDEX_NOT_PROBABILITY"
            if calibration_ready
            else "UNCALIBRATED_CORROBORATED_STYLE_EVIDENCE_INDEX_NOT_PROBABILITY"
        ),
    )
