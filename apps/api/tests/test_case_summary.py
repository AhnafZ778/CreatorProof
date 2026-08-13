from app.domain.enums import MatchStatus
from app.services.evidence import _joint_risk_summary


def _style(tier="LOW"):
    return {"decision": {"evidence_tier": tier}}


def test_no_catalog_match_does_not_hide_visible_ai_label():
    summary = _joint_risk_summary(
        match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES,
        style_analysis=_style(),
        synthetic_analysis={
            "classification": "AI_ORIGIN_MARKER_FOUND",
            "review_recommended": True,
        },
    )

    assert summary["headline"] == "AI origin needs review; no stored-work match"
    assert summary["case_action"] == "REVIEW_ORIGIN"
    assert "human-made" in summary["recommended_action"]


def test_quiet_models_still_do_not_claim_human_origin():
    summary = _joint_risk_summary(
        match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES,
        style_analysis=_style(),
        synthetic_analysis={
            "classification": "NO_AI_ORIGIN_EVIDENCE_DETECTED",
            "review_recommended": False,
        },
    )

    assert summary["headline"] == "No strong AI indicators; no stored-work match"
    assert "not proof of human origin" in summary["recommended_action"]


def test_profile_resemblance_uses_non_attribution_customer_language():
    summary = _joint_risk_summary(
        match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES,
        style_analysis=_style("VERY_HIGH"),
        synthetic_analysis={
            "classification": "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE",
            "review_recommended": False,
        },
    )

    assert summary["classification"] == "STYLE_RESEMBLANCE_ORIGIN_UNRESOLVED"
    assert summary["headline"] == ("Creator-profile resemblance found; AI origin unresolved")
