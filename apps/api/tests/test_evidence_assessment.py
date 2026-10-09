from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.evidence_assessment import assess_evidence_packet
from app.services.evidence_matrix import normalized_signals


def packet(*, exact=False, match="MATCH_FOUND", coverage="COMPLETE"):
    return {
        "decision": {
            "match_status": match,
            "policy_action": "REVIEW",
            "policy_inputs": {
                "rights_facts": {
                    "work_id": "wrk_owned",
                    "authorized": False,
                    "missing_facts": ["NO_RECORDED_LICENSE"],
                    "rights_preferences": {"state": "ACTIVE", "preference": "UNKNOWN"},
                }
            },
        },
        "scope": {"coverage_status": coverage},
        "matches": [
            {
                "work_id": "wrk_owned",
                "exact_sha256": exact,
                "geometry": {"validated": True, "inliers": 68, "inlier_ratio": 0.93},
                "fusion": {"match_supported": match == "MATCH_FOUND", "evidence_index": 0.97},
            },
            {
                "work_id": "wrk_unrelated",
                "exact_sha256": False,
                "fusion": {"match_supported": False, "review_supported": False},
            },
        ],
        "synthetic_origin": {"classification": "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"},
        "provenance": {"status": "NOT_PRESENT"},
        "style_analysis": {
            "provider": "diagnostic-style-signature-v1",
            "top_profiles": [{"creator": "Collection"}],
            "decision": {
                "classification": "DIAGNOSTIC_STYLE_RESEMBLANCE_ONLY",
                "evidence_index": 1.0,
            },
        },
        "proof": {"packet_hash_sha256": "a" * 64},
    }


def assess(p, **kwargs):
    return assess_evidence_packet(p, normalized_signals(p), **kwargs)


@pytest.mark.parametrize("exact,expected", [(True, "EXACT_COPY"), (False, "VALIDATED_REUSE")])
def test_positive_copy_survives_uncertain_retrieval_and_rejected_neighbors(exact, expected):
    p = packet(exact=exact)
    original = deepcopy(p)
    result = assess(p)
    assert result["lanes"]["COPY"]["verdict"] == expected
    assert result["lanes"]["COPY"]["status"] == "SUPPORTED"
    assert result["lanes"]["COPY"]["work_ids"] == ["wrk_owned"]
    assert result["overall"]["verdict"] == "REUSE_CONFIRMED_AUTHORIZATION_UNVERIFIED"
    assert result["lanes"]["RIGHTS"]["status"] == "INCONCLUSIVE"
    assert result["new_inference_performed"] is False
    assert result["overall"]["legal_conclusion"] is None
    assert p == original


def test_positive_member_cannot_override_conflicting_final_match_decision():
    p = packet(exact=True, match="INCONCLUSIVE")
    result = assess(p)
    assert result["lanes"]["COPY"]["verdict"] == "CONFLICTING_REUSE_RESULTS"
    assert result["overall"]["verdict"] == "MISUSE_UNRESOLVED"


@pytest.mark.parametrize(
    "preference,verdict",
    [
        ("DENY", "POTENTIAL_MISUSE_PERMISSION_CONFLICT"),
        ("LICENSE_REQUIRED", "POTENTIAL_MISUSE_REQUIRED_LICENSE"),
        ("UNKNOWN", "REUSE_CONFIRMED_AUTHORIZATION_UNVERIFIED"),
        ("ALLOW", "REUSE_CONFIRMED_AUTHORIZATION_UNVERIFIED"),
    ],
)
def test_misuse_requires_supported_reuse_and_specific_permission_facts(preference, verdict):
    p = packet()
    prefs = p["decision"]["policy_inputs"]["rights_facts"]["rights_preferences"]
    prefs["preference"] = preference
    if preference == "DENY":
        prefs["blocking_reason_codes"] = ["RIGHTS_POLICY_DENIES_DECLARED_USE"]
    assert assess(p)["overall"]["verdict"] == verdict
    p["decision"]["match_status"] = "INCONCLUSIVE"
    p["matches"][0]["fusion"]["match_supported"] = False
    assert assess(p)["overall"]["verdict"] == "MISUSE_UNRESOLVED"


def test_recorded_authorization_and_conflicting_permissions_remain_distinct():
    p = packet()
    rights = p["decision"]["policy_inputs"]["rights_facts"]
    rights.update(authorized=True, authorizing_license_id="lic_confirmed")
    assert assess(p)["overall"]["verdict"] == "RECORDED_AUTHORIZED_REUSE"
    rights["rights_preferences"]["blocking_reason_codes"] = ["RIGHTS_POLICY_DENIES_DECLARED_USE"]
    assert assess(p)["overall"]["verdict"] == "CONFLICTING_PERMISSION_RECORDS"


@pytest.mark.parametrize("change", ["wrong_work", "expired_preference", "missing_license_id"])
def test_permissions_do_not_apply_to_other_work_or_expired_records(change):
    p = packet()
    rights = p["decision"]["policy_inputs"]["rights_facts"]
    if change == "wrong_work":
        rights.update(work_id="wrk_other", authorized=True, authorizing_license_id="lic_other")
    elif change == "expired_preference":
        rights["rights_preferences"].update(
            state="EXPIRED",
            preference="DENY",
            blocking_reason_codes=["RIGHTS_POLICY_DENIES_DECLARED_USE"],
        )
    else:
        rights["authorized"] = True
    assert assess(p)["overall"]["verdict"] == "REUSE_CONFIRMED_AUTHORIZATION_UNVERIFIED"


@pytest.mark.parametrize(
    "origin,status,label",
    [
        ("LIKELY_AI_GENERATED", "SUPPORTED", "Likely AI generated"),
        ("NO_AI_ORIGIN_EVIDENCE_DETECTED", "SUPPORTED", "No AI indicators detected"),
        ("INCONCLUSIVE_DETECTOR_DISAGREEMENT", "INCONCLUSIVE", "AI detectors disagree"),
        ("SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE", "PROVIDER_UNAVAILABLE", "AI origin not assessed"),
    ],
)
def test_origin_assessment_is_specific_and_never_establishes_artwork_misuse(origin, status, label):
    p = packet(match="NO_MATCH_IN_CHECKED_SOURCES")
    p["synthetic_origin"]["classification"] = origin
    result = assess(p)
    assert result["lanes"]["ORIGIN"]["status"] == status
    assert result["lanes"]["ORIGIN"]["label"] == label
    assert result["overall"]["verdict"] == "NO_MISUSE_ESTABLISHED_IN_CHECKED_SOURCES"


def test_negative_result_with_incomplete_coverage_never_clears_misuse():
    p = packet(match="NO_MATCH_IN_CHECKED_SOURCES", coverage="PARTIAL")
    result = assess(p)
    assert result["overall"]["verdict"] == "MISUSE_UNRESOLVED"
    assert result["overall"]["human_review_required"] is True
    assert result["overall"]["tone"] == "review"


def test_diagnostic_style_score_cannot_be_upgraded_to_learned_model_finding():
    p = packet()
    result = assess(p)
    assert result["lanes"]["CREATOR_PROFILE"]["label"] == "Diagnostic resemblance only"
    assert result["lanes"]["CREATOR_PROFILE"]["status"] == "INCONCLUSIVE"
    style = p["style_analysis"]
    style["provider"] = "learned-style-model"
    style["decision"].update(
        classification="HIGH_STYLE_RESEMBLANCE_EVIDENCE",
        learned_style_similarity=0.95,
        false_match_control_supported=True,
    )
    assert assess(p)["lanes"]["CREATOR_PROFILE"]["status"] == "SUPPORTED"
    style["decision"]["false_match_control_supported"] = False
    assert assess(p)["lanes"]["CREATOR_PROFILE"]["status"] == "INCONCLUSIVE"


def test_missing_credentials_are_an_explicit_negative_finding_not_a_stripping_accusation():
    result = assess(packet())
    assert result["lanes"]["PROVENANCE"]["verdict"] == "ABSENT"
    assert result["lanes"]["PROVENANCE"]["label"] == "No Content Credentials found"
    assert "does not establish stripping" in result["lanes"]["PROVENANCE"]["explanation"]


def test_failed_pipeline_does_not_reuse_partial_positive_results():
    result = assess(packet(exact=True), failed=True)
    assert result["overall"]["verdict"] == "ASSESSMENT_FAILED"
    assert not result["overall"]["supported_findings"]
    assert all(lane["status"] == "ERROR" for lane in result["lanes"].values())
