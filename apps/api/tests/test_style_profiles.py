import json

import pytest

from app.api.routes.policies import _recorded_style_policy_inputs
from app.domain.enums import CoverageStatus, MatchStatus, PolicyAction, RightsPath
from app.services.evidence import (
    _style_policy_evidence_tier,
    _style_policy_review_recommended,
)
from app.services.policy_store import evaluate_policy
from app.services.statements import _findings_section
from app.services.style_analysis import _apply_profile_authorization_gate
from app.services.style_profiles import load_style_profile_registry


def _manifest(*profiles):
    return {
        "schema": "creatorproof.style_profile_manifest.v1",
        "manifest_id": "test-profiles-v1",
        "profiles": list(profiles),
    }


def _profile(
    profile_id="profile-a",
    *,
    consent_state="CONFIRMED",
    work_ids=None,
):
    return {
        "profile_id": profile_id,
        "profile_version": "v1",
        "display_name": "Creator A",
        "enrollment_method": "CREATOR_SELECTED_WORKS",
        "consent": {
            "state": consent_state,
            "reference": "consent://test/profile-a/v1",
        },
        "work_ids": work_ids or ["work-a", "work-b"],
    }


def test_confirmed_profile_manifest_maps_work_to_versioned_authorization(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(_manifest(_profile())), encoding="utf-8")

    registry = load_style_profile_registry(path, strict=True)
    binding = registry.binding_for_work("work-b")

    assert registry.state == "VALID"
    assert binding is not None
    assert binding.profile_key == "profile:profile-a:v1"
    assert binding.authorized is True
    assert binding.public_record()["profile_source"] == "REGISTERED_CONSENT_MANIFEST"


def test_work_cannot_be_enrolled_in_multiple_profiles(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            _manifest(
                _profile("profile-a", work_ids=["shared-work"]),
                _profile("profile-b", work_ids=["shared-work"]),
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="multiple style profiles"):
        load_style_profile_registry(path, strict=True)


def test_non_consent_backed_profile_cannot_escalate_policy_review():
    decision = {
        "review_recommended": True,
        "evidence_tier": "HIGH",
        "classification": "HIGH_STYLE_EVIDENCE",
        "reason_codes": ["CORROBORATED_STYLE_FACTORS"],
    }
    profile = {
        "profile_authorized": False,
        "consent_state": "NOT_CONFIRMED",
    }

    gated = _apply_profile_authorization_gate(decision, profile)

    assert gated["review_recommended"] is True
    assert gated["evidence_review_recommended"] is True
    assert gated["evidence_tier"] == "HIGH"
    assert gated["classification"] == "HIGH_STYLE_EVIDENCE"
    assert gated["policy_review_recommended"] is False
    assert gated["policy_escalation_authorized"] is False
    assert gated["policy_classification"] == "STYLE_POLICY_ESCALATION_SUPPRESSED"
    assert "PROFILE_CONSENT_NOT_CONFIRMED" in gated["reason_codes"]
    assert "STYLE_POLICY_ESCALATION_SUPPRESSED" in gated["reason_codes"]


def test_confirmed_profile_preserves_evidence_decision():
    decision = {
        "review_recommended": True,
        "evidence_tier": "HIGH",
        "classification": "HIGH_STYLE_EVIDENCE",
        "reason_codes": ["CORROBORATED_STYLE_FACTORS"],
    }

    gated = _apply_profile_authorization_gate(
        decision,
        {"profile_authorized": True, "consent_state": "CONFIRMED"},
    )

    assert gated["review_recommended"] is True
    assert gated["evidence_review_recommended"] is True
    assert gated["policy_review_recommended"] is True
    assert gated["policy_escalation_authorized"] is True
    assert gated["policy_classification"] == "STYLE_POLICY_REVIEW_RECOMMENDED"
    assert gated["evidence_tier"] == "HIGH"
    assert gated["classification"] == "HIGH_STYLE_EVIDENCE"


def test_low_evidence_keeps_evidence_and_policy_review_false():
    gated = _apply_profile_authorization_gate(
        {
            "review_recommended": False,
            "evidence_tier": "LOW",
            "classification": "LOW_STYLE_RESEMBLANCE_EVIDENCE",
            "reason_codes": [],
        },
        {"profile_authorized": False, "consent_state": "NOT_CONFIRMED"},
    )

    assert gated["review_recommended"] is False
    assert gated["evidence_review_recommended"] is False
    assert gated["policy_review_recommended"] is False
    assert gated["policy_escalation_authorized"] is False
    assert gated["policy_classification"] == "STYLE_POLICY_NO_REVIEW"
    assert gated["evidence_tier"] == "LOW"
    assert "STYLE_POLICY_ESCALATION_SUPPRESSED" not in gated["reason_codes"]


def test_legacy_style_decision_remains_policy_compatible():
    legacy = {"review_recommended": True, "evidence_tier": "HIGH"}

    assert _style_policy_review_recommended(legacy) is True
    assert _style_policy_evidence_tier(legacy) == "HIGH"


def _evaluate_creator_profile_policy(decision):
    return evaluate_policy(
        rules={"escalate_on": {"creator_profile_tier": ["HIGH"]}},
        baseline_action=PolicyAction.PASS_BY_POLICY,
        baseline_reason_codes=["NO_MATCH_IN_DECLARED_CATALOG"],
        match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES,
        coverage_status=CoverageStatus.COMPLETE,
        rights_path=RightsPath.NO_LICENSE_INFO,
        rights_facts={
            "derived_rights_path": str(RightsPath.NO_LICENSE_INFO),
            "missing_facts": [],
        },
        creator_profile_tier=_style_policy_evidence_tier(decision),
        style_review_recommended=_style_policy_review_recommended(decision),
    )


def test_profile_authorization_gates_creator_tier_policy_escalation():
    evidence = {
        "review_recommended": True,
        "evidence_tier": "HIGH",
        "classification": "HIGH_STYLE_RESEMBLANCE_EVIDENCE",
        "reason_codes": [],
    }
    unauthorized = _apply_profile_authorization_gate(
        evidence,
        {"profile_authorized": False, "consent_state": "NOT_CONFIRMED"},
    )
    confirmed = _apply_profile_authorization_gate(
        evidence,
        {"profile_authorized": True, "consent_state": "CONFIRMED"},
    )

    unauthorized_result = _evaluate_creator_profile_policy(unauthorized)
    confirmed_result = _evaluate_creator_profile_policy(confirmed)

    assert unauthorized_result["policy_action"] == str(PolicyAction.PASS_BY_POLICY)
    assert "escalate_on.creator_profile_tier" not in unauthorized_result["matched_rules"]
    assert confirmed_result["policy_action"] == str(PolicyAction.REVIEW)
    assert "escalate_on.creator_profile_tier" in confirmed_result["matched_rules"]


def test_policy_dry_run_replays_only_the_consent_gated_style_projection():
    unauthorized = {
        "style_evidence_tier": "HIGH",
        "style_evidence_review_recommended": True,
        "style_policy_evidence_tier": None,
        "style_policy_review_recommended": False,
        "style_policy_escalation_authorized": False,
    }
    confirmed = {
        **unauthorized,
        "style_policy_evidence_tier": "HIGH",
        "style_policy_review_recommended": True,
        "style_policy_escalation_authorized": True,
    }
    legacy = {
        "style_evidence_tier": "ADVISORY_ONLY",
        "style_review_recommended": False,
    }

    assert _recorded_style_policy_inputs(unauthorized) == (None, False)
    assert _recorded_style_policy_inputs(
        {
            "style_evidence_tier": "HIGH",
            "style_review_recommended": True,
            "style_policy_escalation_authorized": False,
        }
    ) == (None, False)
    assert _recorded_style_policy_inputs(confirmed) == ("HIGH", True)
    assert _recorded_style_policy_inputs(legacy) == ("ADVISORY_ONLY", False)


def test_signed_finding_keeps_evidence_and_policy_governance_separate():
    findings = _findings_section(
        {
            "style_analysis": {
                "customer_facing_lane": "CREATOR_PROFILE_RESEMBLANCE",
                "decision": {
                    "classification": "UNCALIBRATED_STYLE_RESEMBLANCE_REVIEW_CANDIDATE",
                    "evidence_tier": "REVIEW",
                    "review_recommended": True,
                    "evidence_review_recommended": True,
                    "policy_review_recommended": False,
                    "policy_escalation_authorized": False,
                    "policy_classification": "STYLE_POLICY_ESCALATION_SUPPRESSED",
                },
            }
        }
    )["creator_profile_resemblance"]

    assert findings["evidence_tier"] == "REVIEW"
    assert findings["evidence_review_recommended"] is True
    assert findings["policy_review_recommended"] is False
    assert findings["policy_escalation_authorized"] is False
    assert findings["policy_classification"] == "STYLE_POLICY_ESCALATION_SUPPRESSED"
