from types import SimpleNamespace

from app.domain.enums import ClaimState, MatchStatus, PolicyAction, RightsPath
from app.services.evidence import CandidateEvidence, _decision, _policy


def _candidate(*, match_supported=False, review_supported=False):
    return CandidateEvidence(
        work_id="wrk_test",
        title="Test work",
        retrieval_rank=1,
        retrieval_provider="phash-fallback",
        retrieval_score=0.1,
        ai_similarity=None,
        exact_sha256=False,
        phash_distance=32,
        phash_similarity=0.5,
        geometry={},
        aligned_perceptual={},
        fusion={
            "match_supported": match_supported,
            "review_supported": review_supported,
            "evidence_index": 0.0,
        },
        visualization={},
        copy_evidence_score=0.0,
        prototype_evidence_score=0.0,
        verification_state="NO_VERIFIED_COPY",
    )


def test_no_match_requires_complete_coverage():
    incomplete_scope = {"coverage_status": "TRUNCATED", "complete_for_declared_catalog": False}
    complete_scope = {"coverage_status": "COMPLETE", "complete_for_declared_catalog": True}

    assert _decision(None, incomplete_scope) == MatchStatus.SCOPE_INCOMPLETE
    assert _decision(_candidate(), incomplete_scope) == MatchStatus.SCOPE_INCOMPLETE
    assert _decision(_candidate(), complete_scope) == MatchStatus.NO_MATCH_IN_CHECKED_SOURCES


def test_positive_match_remains_reportable_when_scope_is_incomplete():
    incomplete_scope = {"coverage_status": "TRUNCATED", "complete_for_declared_catalog": False}

    assert _decision(_candidate(match_supported=True), incomplete_scope) == MatchStatus.MATCH_FOUND


def test_positive_match_with_incomplete_scope_cannot_auto_pass():
    work = SimpleNamespace(
        rights_path=RightsPath.EXISTING_LICENSE,
        allowed_uses=["marketing/social"],
        claim_state=ClaimState.CORROBORATED,
    )

    action, rights_path, reasons = _policy(
        MatchStatus.MATCH_FOUND,
        work,
        "marketing/social",
        coverage_status="TRUNCATED",
        coverage_reason_codes=["CANDIDATE_VERIFICATION_TRUNCATED"],
    )

    assert action == PolicyAction.REVIEW
    assert rights_path == RightsPath.EXISTING_LICENSE
    assert "MATCH_FOUND_WITH_INCOMPLETE_SCOPE_REQUIRES_REVIEW" in reasons
    assert "CANDIDATE_VERIFICATION_TRUNCATED" in reasons


def test_incomplete_scope_policy_is_always_review():
    action, rights_path, reasons = _policy(
        MatchStatus.SCOPE_INCOMPLETE,
        None,
        "marketing/social",
        coverage_reason_codes=["CANDIDATE_VERIFICATION_TRUNCATED"],
    )

    assert action == PolicyAction.REVIEW
    assert rights_path == RightsPath.NO_LICENSE_INFO
    assert "SCOPE_INCOMPLETE_REQUIRES_REVIEW" in reasons
    assert "CANDIDATE_VERIFICATION_TRUNCATED" in reasons


def test_only_corroborated_claim_can_authorize_recorded_license():
    base = {
        "rights_path": RightsPath.EXISTING_LICENSE,
        "allowed_uses": ["marketing/social"],
    }
    for state in (
        ClaimState.ASSERTED,
        ClaimState.DISPUTED,
        ClaimState.SUPERSEDED,
        ClaimState.REVOKED,
    ):
        work = SimpleNamespace(**base, claim_state=state)
        action, _, _ = _policy(MatchStatus.MATCH_FOUND, work, "marketing/social")
        assert action == PolicyAction.REVIEW

    corroborated = SimpleNamespace(**base, claim_state=ClaimState.CORROBORATED)
    action, rights_path, reasons = _policy(
        MatchStatus.MATCH_FOUND,
        corroborated,
        "marketing/social",
    )
    assert action == PolicyAction.PASS_BY_POLICY
    assert rights_path == RightsPath.EXISTING_LICENSE
    assert reasons == ["MATCHED_USE_ALLOWED_BY_RIGHTS_RECORD"]
