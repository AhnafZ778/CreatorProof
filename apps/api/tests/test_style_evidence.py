import numpy as np

from app.core.config import Settings
from app.domain.enums import MatchStatus, OriginPolicyMode, PolicyAction
from app.services.evidence import _apply_style_policy_overlay
from app.services.style_fusion import fuse_style_evidence
from app.services.style_readout import (
    aggregated_discrimination_gaps,
    catalog_relative_empirical_support,
    corpus_profile_readout,
    normalize,
)


def _tile_map(score: float) -> dict:
    cells = [{"score": score} for _ in range(16)]
    return {"query_cells": cells, "reference_cells": cells}


def test_corpus_readout_emits_raw_and_csls_without_self_density_bias():
    vectors = {
        "a1": normalize(np.array([1.0, 0.0])),
        "a2": normalize(np.array([0.9, 0.4359])),
        "b1": normalize(np.array([0.20, 0.98])),
    }
    groups = {"artist-a": ["a1", "a2"], "artist-b": ["b1"]}
    result = corpus_profile_readout(normalize(np.array([0.98, 0.10])), vectors, groups, csls_k=2)

    assert result["artist-a"]["raw_pool_similarity"] > result["artist-b"]["raw_pool_similarity"]
    assert result["artist-a"]["csls_score"] is not None
    assert result["artist-a"]["csls_k_effective"] == 2
    assert result["artist-a"]["anchor_local_density"] < 1.0


def test_discrimination_gap_detects_catalog_inversion():
    vectors = {
        "a1": normalize(np.array([1.0, 0.0])),
        "a2": normalize(np.array([0.0, 1.0])),
        "b1": normalize(np.array([1.0, 1.0])),
    }
    result = aggregated_discrimination_gaps(vectors, {"artist-a": ["a1", "a2"], "artist-b": ["b1"]})

    assert result["artist-a"]["discrimination_gap"] < 0
    assert result["artist-a"]["worst_cross_profile_key"] == "artist-b"
    assert result["artist-b"]["discrimination_gap"] is None


def test_uncalibrated_style_fusion_cannot_claim_high_confidence():
    result = fuse_style_evidence(
        learned_provider_active=True,
        raw_style_similarity=0.819,
        factors={
            "palette": 0.646,
            "tone": 0.845,
            "stroke_orientation": 0.941,
            "texture": 0.892,
        },
        tile_map=_tile_map(0.778),
        content_similarity=0.453,
        sample_count=3,
        discrimination_gap=0.08,
        catalog_margin=0.06,
        settings=Settings(),
    )

    assert 0.82 < result.evidence_index < 0.86
    assert result.evidence_tier == "REVIEW"
    assert result.review_recommended is True
    assert result.false_match_control_supported is False
    assert result.content_confound_state == "STYLE_EXCEEDS_CONTENT_CONTROL"
    assert "STYLE_EXCEEDS_CONTENT_CONTROL" in result.reason_codes


def test_catalog_calibration_can_promote_well_supported_style_evidence():
    result = fuse_style_evidence(
        learned_provider_active=True,
        raw_style_similarity=0.90,
        factors={
            "palette": 0.78,
            "tone": 0.88,
            "stroke_orientation": 0.94,
            "texture": 0.93,
        },
        tile_map=_tile_map(0.86),
        content_similarity=0.40,
        sample_count=4,
        discrimination_gap=0.18,
        catalog_margin=0.12,
        calibration={
            "ready": True,
            "state": "CATALOG_RELATIVE_EMPIRICAL_SUPPORT_READY",
            "selection_correction": "BONFERRONI_FAMILY_WISE_V1",
            "negative_tail_p_raw": 0.013,
            "negative_tail_p": 0.04,
            "positive_support_percentile": 0.80,
        },
        settings=Settings(),
    )

    assert result.evidence_tier in {"HIGH", "VERY_HIGH"}
    assert result.false_match_control_supported is True
    assert result.calibration_state == "CATALOG_RELATIVE_EMPIRICAL_SUPPORT_READY"


def test_catalog_empirical_tail_uses_cross_creator_negatives():
    vectors = {
        "a1": normalize(np.array([1.0, 0.02, 0.0])),
        "a2": normalize(np.array([0.99, -0.03, 0.0])),
        "a3": normalize(np.array([0.98, 0.04, 0.0])),
    }
    groups = {"artist-a": ["a1", "a2", "a3"]}
    for index in range(20):
        item_id = f"negative-{index}"
        angle = index / 20 * np.pi
        vectors[item_id] = normalize(np.array([0.05, np.cos(angle), np.sin(angle)]))
        groups.setdefault("artist-b" if index < 10 else "artist-c", []).append(item_id)

    result = catalog_relative_empirical_support(
        0.97,
        vectors,
        groups,
        "artist-a",
        min_profile_works=3,
        min_profiles=3,
        min_negatives=19,
    )

    assert result["ready"] is True
    assert result["negative_calibration_count"] == 20
    assert result["negative_tail_p_raw"] < 0.05
    assert result["negative_tail_p"] > result["negative_tail_p_raw"]
    assert result["negative_tail_p"] == result["negative_tail_p_selection_adjusted"]
    assert result["selection_count"] == 3


def test_style_fusion_rejects_unadjusted_selected_profile_p_value():
    result = fuse_style_evidence(
        learned_provider_active=True,
        raw_style_similarity=0.94,
        factors={
            "palette": 0.90,
            "tone": 0.94,
            "stroke_orientation": 0.96,
            "texture": 0.95,
        },
        tile_map=_tile_map(0.92),
        content_similarity=0.30,
        sample_count=5,
        discrimination_gap=0.20,
        catalog_margin=0.15,
        calibration={
            "ready": True,
            "state": "CATALOG_RELATIVE_EMPIRICAL_SUPPORT_READY",
            "negative_tail_p": 0.01,
            "positive_support_percentile": 0.90,
        },
        settings=Settings(),
    )

    assert result.evidence_tier == "REVIEW"
    assert result.false_match_control_supported is False
    assert "STYLE_SELECTION_CORRECTION_REQUIRED" in result.reason_codes


def test_diagnostic_fallback_never_triggers_creator_policy_review():
    result = fuse_style_evidence(
        learned_provider_active=False,
        raw_style_similarity=None,
        factors={
            "palette": 0.95,
            "tone": 0.95,
            "stroke_orientation": 0.95,
            "texture": 0.95,
        },
        tile_map=_tile_map(0.95),
        content_similarity=None,
        sample_count=5,
        discrimination_gap=0.20,
        catalog_margin=0.20,
        settings=Settings(),
    )

    assert result.evidence_tier == "DIAGNOSTIC"
    assert result.review_recommended is False
    assert "DIAGNOSTIC_FALLBACK_CANNOT_ATTRIBUTE_CREATOR" in result.reason_codes


def test_style_signal_alone_does_not_escalate_policy_or_manufacture_copy_match():
    action, reasons, style_review = _apply_style_policy_overlay(
        match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES,
        policy_action=PolicyAction.PASS_BY_POLICY,
        reason_codes=["NO_MATCH_IN_DECLARED_CATALOG"],
        style_analysis={"decision": {"review_recommended": True}},
    )

    assert action == PolicyAction.PASS_BY_POLICY
    assert style_review is True
    assert "STYLE_SIGNAL_NOT_AUTO_ESCALATED_WITHOUT_AI_ORIGIN_SUPPORT" in reasons


def test_ai_origin_plus_calibrated_style_routes_human_review_without_copy_claim():
    action, reasons, style_review = _apply_style_policy_overlay(
        match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES,
        policy_action=PolicyAction.PASS_BY_POLICY,
        reason_codes=["NO_MATCH_IN_DECLARED_CATALOG"],
        style_analysis={"decision": {"review_recommended": True, "evidence_tier": "HIGH"}},
        synthetic_analysis={"classification": "LIKELY_AI_GENERATED"},
        origin_policy_mode=OriginPolicyMode.REQUIRED,
    )

    assert action == PolicyAction.REVIEW
    assert style_review is True
    assert "AI_ORIGIN_AND_STYLE_RESEMBLANCE_REVIEW_RECOMMENDED" in reasons
    assert "STYLE_REVIEW_IS_NOT_COPY_OR_INFRINGEMENT_FINDING" in reasons


def test_unresolved_ai_origin_routes_review_even_without_catalog_match():
    action, reasons, style_review = _apply_style_policy_overlay(
        match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES,
        policy_action=PolicyAction.PASS_BY_POLICY,
        reason_codes=["NO_MATCH_IN_DECLARED_CATALOG"],
        style_analysis={"decision": {"review_recommended": False}},
        synthetic_analysis={
            "classification": "AI_ORIGIN_MARKER_FOUND",
            "review_recommended": True,
        },
        origin_policy_mode=OriginPolicyMode.REQUIRED,
    )

    assert action == PolicyAction.REVIEW
    assert style_review is False
    assert "AI_ORIGIN_RESULT_REQUIRES_PRODUCT_REVIEW" in reasons
    assert "AI_ORIGIN_REVIEW_IS_NOT_INFRINGEMENT_FINDING" in reasons


def test_informational_ai_origin_never_changes_policy_action():
    action, reasons, style_review = _apply_style_policy_overlay(
        match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES,
        policy_action=PolicyAction.PASS_BY_POLICY,
        reason_codes=["NO_MATCH_IN_DECLARED_CATALOG"],
        style_analysis={"decision": {"review_recommended": True, "evidence_tier": "HIGH"}},
        synthetic_analysis={
            "classification": "AI_ORIGIN_MARKER_FOUND",
            "review_recommended": True,
        },
        origin_policy_mode=OriginPolicyMode.INFORMATIONAL,
    )

    assert action == PolicyAction.PASS_BY_POLICY
    assert style_review is True
    assert "AI_ORIGIN_INFORMATIONAL_ONLY" in reasons
    assert "AI_ORIGIN_RESULT_REQUIRES_PRODUCT_REVIEW" not in reasons


def test_style_review_does_not_override_a_licensed_copy_policy():
    action, reasons, style_review = _apply_style_policy_overlay(
        match_status=MatchStatus.MATCH_FOUND,
        policy_action=PolicyAction.PASS_BY_POLICY,
        reason_codes=["MATCHED_USE_ALLOWED_BY_RIGHTS_RECORD"],
        style_analysis={"decision": {"review_recommended": True}},
    )

    assert action == PolicyAction.PASS_BY_POLICY
    assert reasons == ["MATCHED_USE_ALLOWED_BY_RIGHTS_RECORD"]
    assert style_review is True
