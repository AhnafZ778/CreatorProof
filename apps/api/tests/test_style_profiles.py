import json

import pytest

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

    assert gated["review_recommended"] is False
    assert gated["evidence_tier"] == "ADVISORY_ONLY"
    assert gated["classification"] == "PROFILE_ENROLLMENT_NOT_CONSENT_BACKED"
    assert "STYLE_POLICY_ESCALATION_SUPPRESSED" in gated["reason_codes"]


def test_confirmed_profile_preserves_evidence_decision():
    decision = {"review_recommended": True, "evidence_tier": "HIGH"}

    assert (
        _apply_profile_authorization_gate(
            decision,
            {"profile_authorized": True, "consent_state": "CONFIRMED"},
        )
        == decision
    )
