"""Rights preferences constrain review but never manufacture authorization."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.enums import CoverageStatus, MatchStatus, PolicyAction, RightsPath
from app.models import Work
from app.services.policy_store import collect_rights_facts, evaluate_policy
from app.services.rights_baseline import ensure_unknown_rights_baseline


@pytest.fixture
def policy_work(client):
    container = client.app.state.container
    db = container.database.session_factory()
    row = Work(
        id="wrk_preferences",
        tenant_id=container.settings.dev_tenant_id,
        catalog_id="preferences",
        title="Preferences",
        sha256="a" * 64,
        phash="0" * 16,
        storage_key="preferences.png",
    )
    db.add(row)
    db.flush()
    ensure_unknown_rights_baseline(db, work=row)
    db.commit()
    db.close()
    return row.id


def _policy(client, api_key, work_id, payload):
    response = client.post(
        f"/v1/works/{work_id}/rights-policy", headers={"X-API-Key": api_key}, json=payload
    )
    assert response.status_code == 201, response.text


def _license(client, api_key, work_id, *, intended_use="AI training", **scope):
    headers = {"X-API-Key": api_key}
    claim = client.post(
        "/v1/rights/claims",
        headers=headers,
        json={"work_id": work_id, "claimant_label": "Creator assertion"},
    )
    assert claim.status_code == 201, claim.text
    corroborated = client.post(
        f"/v1/rights/claims/{claim.json()['id']}/events",
        headers=headers,
        json={"event_type": "CORROBORATED", "reason": "Recorded corroboration evidence"},
    )
    assert corroborated.status_code in {200, 201}, corroborated.text
    response = client.post(
        "/v1/rights/licenses",
        headers=headers,
        json={
            "work_id": work_id,
            "claim_id": claim.json()["id"],
            "permitted_uses": [intended_use],
            **scope,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _evaluate(
    client,
    work_id,
    *,
    intended_use="AI training",
    scope_context=None,
    block=False,
    match_status=MatchStatus.MATCH_FOUND,
):
    container = client.app.state.container
    db = container.database.session_factory()
    facts = collect_rights_facts(
        db,
        tenant_id=container.settings.dev_tenant_id,
        work_id=work_id,
        intended_use=intended_use,
        scope_context=scope_context,
    )
    result = evaluate_policy(
        rules={"block_enabled": block},
        baseline_action=PolicyAction.REVIEW,
        baseline_reason_codes=[],
        match_status=match_status,
        coverage_status=CoverageStatus.COMPLETE,
        rights_path=RightsPath.NO_LICENSE_INFO,
        rights_facts=facts,
    )
    db.close()
    return facts, result


def test_registration_unknown_baseline_is_versioned_idempotent_and_not_creator_consent(
    client, api_key, policy_work
):
    from sqlalchemy import func, select

    from app.models import RightsPolicyVersion
    from app.services.canonical import canonical_digest
    from app.services.rights_baseline import is_unknown_rights_baseline
    from app.services.rights_passport import PERMISSION_FIELDS, policy_integrity_projection

    db = client.app.state.container.database.session_factory()
    work = db.get(Work, policy_work)
    first = ensure_unknown_rights_baseline(db, work=work)
    second = ensure_unknown_rights_baseline(db, work=work)
    assert first.id == second.id
    assert first.version == 1
    assert first.permissions == {field: "UNKNOWN" for field in PERMISSION_FIELDS}
    assert first.creator_assertions["status"] == "UNKNOWN"
    assert first.creator_assertions["creator_id"] is None
    assert first.consent_metadata["status"] == "UNKNOWN"
    assert first.revocation_metadata["status"] == "UNKNOWN"
    assert is_unknown_rights_baseline(first)
    assert canonical_digest(policy_integrity_projection(first)) == first.digest_sha256
    assert db.scalar(select(func.count()).select_from(RightsPolicyVersion)) == 1
    db.close()
    facts, decision = _evaluate(client, policy_work)
    assert facts["rights_preferences"]["source"] == "SYSTEM_UNKNOWN_BASELINE_NOT_AUTHORIZATION"
    assert facts["authorized"] is False
    assert decision["policy_action"] == "REVIEW"
    passport = client.get(
        f"/v1/works/{policy_work}/rights-policy", headers={"X-API-Key": api_key}
    ).json()
    assert passport["policy"]["version"] == 1
    assert passport["policy"]["creator_assertion_status"] == "UNKNOWN"


def test_neutral_registration_baseline_does_not_override_authoritative_license(
    client, api_key, policy_work
):
    _license(client, api_key, policy_work)
    facts, decision = _evaluate(client, policy_work)
    assert facts["rights_preferences"]["preference"] == "UNKNOWN"
    assert facts["rights_preferences"]["missing_facts"] == []
    assert facts["authorized"] is True
    assert decision["policy_action"] == "PASS_BY_POLICY"


def test_creator_unknown_assertion_cannot_spoof_server_baseline_envelope(
    client, api_key, policy_work
):
    _license(client, api_key, policy_work)
    _policy(
        client,
        api_key,
        policy_work,
        {
            "creator_assertion_status": "UNKNOWN",
            "creator_assertion": {"baseline_source": "SYSTEM_REGISTRATION_UNKNOWN"},
        },
    )
    facts, decision = _evaluate(client, policy_work)
    assert facts["rights_preferences"]["source"] == "CREATOR_ASSERTION_NOT_AUTHORIZATION"
    assert "RIGHTS_POLICY_PERMISSION_UNKNOWN" in facts["rights_preferences"]["missing_facts"]
    assert decision["policy_action"] == "REVIEW"


def test_permission_allow_is_self_assertion_not_authorizing_licence(client, api_key, policy_work):
    _policy(client, api_key, policy_work, {"AI_training_permission": "ALLOW"})
    facts, result = _evaluate(client, policy_work)
    assert facts["rights_preferences"]["preference"] == "ALLOW"
    assert facts["rights_preferences"]["source"] == "CREATOR_ASSERTION_NOT_AUTHORIZATION"
    assert facts["authorized"] is False
    assert result["policy_action"] == "REVIEW"


def test_copy_match_with_effective_verified_licence_and_allow_passes(client, api_key, policy_work):
    license_id = _license(client, api_key, policy_work)
    _policy(client, api_key, policy_work, {"AI_training_permission": "ALLOW"})
    facts, result = _evaluate(client, policy_work)
    assert facts["authorized"] is True
    assert result["policy_action"] == "PASS_BY_POLICY"
    assert result["authorizing_license_id"] == license_id


@pytest.mark.parametrize("block, expected", [(False, "REVIEW"), (True, "BLOCK")])
def test_denied_use_requires_review_or_enabled_organization_block(
    client, api_key, policy_work, block, expected
):
    _license(client, api_key, policy_work)
    _policy(client, api_key, policy_work, {"AI_training_permission": "DENY"})
    facts, result = _evaluate(client, policy_work, block=block)
    assert "RIGHTS_POLICY_DENIES_DECLARED_USE" in facts["blocking_reason_codes"]
    assert result["policy_action"] == expected


def test_license_required_preference_never_passes_without_licence(client, api_key, policy_work):
    _policy(client, api_key, policy_work, {"AI_training_permission": "LICENSE_REQUIRED"})
    facts, result = _evaluate(client, policy_work)
    assert facts["rights_preferences"]["license_required"] is True
    assert result["policy_action"] == "REVIEW"
    assert "RIGHTS_POLICY_LICENSE_REQUIRED" in result["reason_codes"]


def test_license_required_preference_passes_with_in_scope_verified_licence(
    client, api_key, policy_work
):
    _license(client, api_key, policy_work)
    _policy(client, api_key, policy_work, {"AI_training_permission": "LICENSE_REQUIRED"})
    _, result = _evaluate(client, policy_work)
    assert result["policy_action"] == "PASS_BY_POLICY"


@pytest.mark.parametrize(
    "payload, reason",
    [
        (
            {"effective_until": (datetime.now(UTC) - timedelta(days=1)).isoformat()},
            "RIGHTS_POLICY_EXPIRED",
        ),
        (
            {"effective_from": (datetime.now(UTC) + timedelta(days=1)).isoformat()},
            "RIGHTS_POLICY_NOT_YET_EFFECTIVE",
        ),
        (
            {"revocation_status": "REVOKED", "revocation_timestamp": datetime.now(UTC).isoformat()},
            "RIGHTS_POLICY_REVOKED",
        ),
        ({"consent_status": "WITHDRAWN"}, "RIGHTS_POLICY_CONSENT_WITHDRAWN"),
    ],
)
def test_inactive_policy_does_not_silently_reuse_prior_permission(
    client, api_key, policy_work, payload, reason
):
    _license(client, api_key, policy_work)
    _policy(client, api_key, policy_work, {"AI_training_permission": "ALLOW", **payload})
    facts, result = _evaluate(client, policy_work)
    assert reason in facts["missing_facts"]
    assert result["policy_action"] == "REVIEW"


@pytest.mark.parametrize(
    "scope, context, reason",
    [
        ({"geographic_scope": ["US"]}, {"territory": "DE"}, "RIGHTS_POLICY_GEOGRAPHY_MISMATCH"),
        ({"geographic_scope": ["US"]}, {}, "RIGHTS_POLICY_GEOGRAPHY_CONTEXT_MISSING"),
        (
            {"permitted_platforms": ["allowed"]},
            {"platform": "other"},
            "RIGHTS_POLICY_PLATFORM_MISMATCH",
        ),
        (
            {"prohibited_platforms": ["blocked"]},
            {"platform": "blocked"},
            "RIGHTS_POLICY_PLATFORM_PROHIBITED",
        ),
        ({"permitted_models": ["model-a"]}, {"model": "model-b"}, "RIGHTS_POLICY_MODEL_MISMATCH"),
        (
            {"prohibited_models": ["model-b"]},
            {"model": "model-b"},
            "RIGHTS_POLICY_MODEL_PROHIBITED",
        ),
    ],
)
def test_passport_scope_mismatch_or_missing_context_never_passes(
    client, api_key, policy_work, scope, context, reason
):
    _license(client, api_key, policy_work)
    _policy(client, api_key, policy_work, {"AI_training_permission": "ALLOW", **scope})
    facts, result = _evaluate(client, policy_work, scope_context=context)
    assert reason in facts["blocking_reason_codes"] + facts["missing_facts"]
    assert result["policy_action"] == "REVIEW"


def test_licence_territory_channel_audience_transformation_are_enforced(
    client, api_key, policy_work
):
    _license(
        client,
        api_key,
        policy_work,
        territories=["US"],
        channels=["web"],
        audiences=["public"],
        transformations=["none"],
    )
    _policy(client, api_key, policy_work, {"AI_training_permission": "ALLOW"})
    context = {"territory": "US", "channel": "web", "audience": "public", "transformation": "none"}
    _, matching = _evaluate(client, policy_work, scope_context=context)
    assert matching["policy_action"] == "PASS_BY_POLICY"
    for key, reason in [
        ("territory", "LICENSE_TERRITORY_MISMATCH"),
        ("channel", "LICENSE_CHANNEL_MISMATCH"),
        ("audience", "LICENSE_AUDIENCE_MISMATCH"),
        ("transformation", "LICENSE_TRANSFORMATION_MISMATCH"),
    ]:
        facts, mismatch = _evaluate(client, policy_work, scope_context={**context, key: "other"})
        assert reason in facts["license_reason_codes"]
        assert mismatch["policy_action"] == "REVIEW"
    _, absent = _evaluate(client, policy_work)
    assert absent["policy_action"] == "REVIEW"


def test_intended_use_mismatch_is_not_authorized_by_other_licence(client, api_key, policy_work):
    _license(client, api_key, policy_work, intended_use="marketing/social")
    _policy(client, api_key, policy_work, {"AI_training_permission": "ALLOW"})
    facts, result = _evaluate(client, policy_work)
    assert "LICENSE_DOES_NOT_LIST_INTENDED_USE" in facts["license_reason_codes"]
    assert result["policy_action"] == "REVIEW"


def test_style_or_no_copy_result_cannot_be_blocked_by_rights_preferences(
    client, api_key, policy_work
):
    _policy(client, api_key, policy_work, {"AI_training_permission": "DENY"})
    _, result = _evaluate(
        client, policy_work, block=True, match_status=MatchStatus.NO_MATCH_IN_CHECKED_SOURCES
    )
    assert result["policy_action"] != "BLOCK"
    assert result["inputs"]["match_status"] == "NO_MATCH_IN_CHECKED_SOURCES"
