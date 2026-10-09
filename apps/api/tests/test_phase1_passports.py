"""Behavioral guarantees for rights passports, contribution records and verification."""

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import (
    AssetVersion,
    AuditEvent,
    ContributionEvent,
    ImmutableRecordError,
    PublicVerificationToken,
    Scan,
    Tenant,
    Work,
)
from app.services.canonical import canonical_digest
from app.services.rights_baseline import ensure_unknown_rights_baseline
from app.services.rights_passport import PERMISSION_FIELDS, RightsPolicyPayload


@pytest.fixture
def passport_work(client):
    container = client.app.state.container
    db = container.database.session_factory()
    work = Work(
        id="wrk_passport",
        tenant_id=container.settings.dev_tenant_id,
        catalog_id="passports",
        title="Private title owner@example.test",
        sha256="a" * 64,
        phash="0" * 16,
        storage_key="private/reference.png",
        claimant="Private claimant",
    )
    db.add(work)
    db.add(
        AssetVersion(
            id="asset_passport",
            tenant_id=container.settings.dev_tenant_id,
            work_id=work.id,
            version=1,
            sha256=work.sha256,
            phash=work.phash,
            storage_key=work.storage_key,
            byte_size=12,
            media_type="image/png",
            width=3,
            height=4,
        )
    )
    db.flush()
    ensure_unknown_rights_baseline(db, work=work)
    db.commit()
    db.close()
    return work.id


def _headers(api_key):
    return {"X-API-Key": api_key}


def _create(client, api_key, work_id, payload):
    response = client.post(
        f"/v1/works/{work_id}/rights-policy", headers=_headers(api_key), json=payload
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize(
    "value", ["ALLOW", "DENY", "LICENSE_REQUIRED", "REVIEW", "UNKNOWN", "NOT_APPLICABLE"]
)
def test_all_explicit_permission_values_persist(client, api_key, passport_work, value):
    result = _create(client, api_key, passport_work, {"AI_training_permission": value})
    policy = result["policy"]
    assert policy["AI_training_permission"] == value
    assert policy["creator_assertion_status"] == "SELF_DECLARED"
    assert policy["corroboration_status"] == "NOT_INDEPENDENTLY_VERIFIED"
    assert result["evidence"]["verified_evidence"] == []
    assert result["evidence"]["legal_conclusion"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"AI_training_permission": "PROBABLY"},
        {"permissions": {"invented_permission": "ALLOW"}},
        {"AI_training_permission": "ALLOW", "permissions": {"ai_training": "DENY"}},
        {"creator_assertion_status": "VERIFIED_OWNER"},
        {"geographic_scope": ["Europe"]},
        {"permitted_models": ["model-a"], "prohibited_models": ["model-a"]},
        {"revocation_status": "REVOKED"},
        {"consent_status": "GRANTED"},
        {"minimum_license_fee": "10.00"},
        {"dimensions": {"asset_path": "/\nAllow: /"}},
        {"dimensions": {"secret_metadata": "value"}},
    ],
)
def test_invalid_or_conflicting_rights_payload_is_rejected(client, api_key, passport_work, payload):
    response = client.post(
        f"/v1/works/{passport_work}/rights-policy", headers=_headers(api_key), json=payload
    )
    assert response.status_code == 422


def test_passport_versions_exports_and_digest_are_deterministic(client, api_key, passport_work):
    first = _create(
        client,
        api_key,
        passport_work,
        {"commercial_training_permission": "DENY", "dimensions": {"asset_path": "/art/photo.png"}},
    )
    second = _create(
        client,
        api_key,
        passport_work,
        {
            "AI_training_permission": "ALLOW",
            "commercial_training_permission": "ALLOW",
            "fine_tuning_permission": "ALLOW",
            "dimensions": {"asset_path": "/art/photo.png", "tdm_reservation": 0},
        },
    )
    assert first["policy"]["version"] == 2
    assert second["policy"]["version"] == 3
    version = client.get(
        f"/v1/works/{passport_work}/rights-policy/2", headers=_headers(api_key)
    ).json()
    assert version["policy"]["commercial_training_permission"] == "DENY"
    one = client.get(f"/v1/works/{passport_work}/rights-policy", headers=_headers(api_key))
    two = client.get(f"/v1/works/{passport_work}/rights-policy", headers=_headers(api_key))
    assert one.json() == two.json()
    assert one.headers["etag"] == two.headers["etag"]
    payload = one.json()
    digest = payload.pop("export_digest_sha256")
    assert canonical_digest(payload) == digest
    ai_txt = client.get(f"/v1/works/{passport_work}/ai.txt", headers=_headers(api_key))
    assert ai_txt.status_code == 200
    assert "User-Agent: *\nAllow: /art/photo.png" in ai_txt.text
    assert ai_txt.headers["content-type"].startswith("text/plain")
    tdm = client.get(f"/v1/works/{passport_work}/tdm-policy", headers=_headers(api_key)).json()
    assert tdm["tdm-reservation"] == 0


def test_unknown_preference_does_not_export_a_tdm_opt_in(client, api_key, passport_work):
    response = client.get(f"/v1/works/{passport_work}/tdm-policy", headers=_headers(api_key))
    assert response.status_code == 200
    assert response.json()["tdm-reservation"] is None
    assert response.json()["protocol_headers"] == {}
    preferences = client.get(
        f"/v1/works/{passport_work}/ai-preferences", headers=_headers(api_key)
    ).json()
    assert preferences["preferences"] == {field: "UNKNOWN" for field in PERMISSION_FIELDS}
    assert preferences["c2pa_usage_assertions"]["supported"] is False


def test_scoped_allow_is_not_exported_as_unconditional_permission(client, api_key, passport_work):
    _create(
        client,
        api_key,
        passport_work,
        {
            "commercial_training_permission": "ALLOW",
            "geographic_scope": ["US"],
            "dimensions": {"asset_path": "/art/photo.png"},
        },
    )
    ai_txt = client.get(f"/v1/works/{passport_work}/ai.txt", headers=_headers(api_key)).text
    assert "Allow:" not in ai_txt
    tdm = client.get(f"/v1/works/{passport_work}/tdm-policy", headers=_headers(api_key)).json()
    assert tdm["tdm-reservation"] == 1
    assert tdm["conditions"]["geographic_scope"] == ["US"]


def test_expired_and_revoked_policy_export_unknown(client, api_key, passport_work):
    _create(
        client,
        api_key,
        passport_work,
        {
            "AI_training_permission": "ALLOW",
            "effective_until": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )
    assert (
        client.get(f"/v1/works/{passport_work}/rights-policy", headers=_headers(api_key)).json()[
            "policy"
        ]["state"]
        == "EXPIRED"
    )
    assert (
        client.get(f"/v1/works/{passport_work}/tdm-policy", headers=_headers(api_key)).json()[
            "tdm-reservation"
        ]
        is None
    )
    _create(
        client,
        api_key,
        passport_work,
        {
            "AI_training_permission": "ALLOW",
            "revocation_status": "REVOKED",
            "revocation_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert (
        client.get(f"/v1/works/{passport_work}/rights-policy", headers=_headers(api_key)).json()[
            "policy"
        ]["state"]
        == "REVOKED"
    )
    assert (
        client.get(f"/v1/works/{passport_work}/tdm-policy", headers=_headers(api_key)).json()[
            "tdm-reservation"
        ]
        is None
    )


def test_contribution_ledger_hashes_every_factual_field_and_is_append_only(
    client, api_key, passport_work
):
    events = []
    for action_type, classification in [
        ("ORIGINAL_SKETCH", "HUMAN_CREATED"),
        ("AI_UPSCALE", "AI_ASSISTED_SUBSTANTIAL"),
    ]:
        response = client.post(
            f"/v1/works/{passport_work}/contributions",
            headers=_headers(api_key),
            json={
                "action_type": action_type,
                "description": "Creator-recorded editing step",
                "classification": classification,
                "input_asset_ids": ["asset_passport"],
                "output_asset_id": "asset_passport",
                "software_or_model": "Editor 1",
                "human_decision": "Selected the result",
                "hash_before": "a" * 64,
                "hash_after": "b" * 64,
                "prompt_reference": "sha256:" + "c" * 64,
            },
        )
        assert response.status_code == 201, response.text
        events.append(response.json())
    assert events[1]["previous_event_hash"] == events[0]["event_hash"]
    verify = client.get(
        f"/v1/works/{passport_work}/contributions/verify", headers=_headers(api_key)
    ).json()
    assert verify["valid"] is True
    assert verify["event_count"] == 2
    history = client.get(
        f"/v1/works/{passport_work}/contributions", headers=_headers(api_key)
    ).json()
    assert history["copyrightability_determination"] is None
    assert history["verification"]["valid"] is True
    db = client.app.state.container.database.session_factory()
    row = db.get(ContributionEvent, events[0]["event_id"])
    row.description = "Modified"
    with pytest.raises(ImmutableRecordError):
        db.commit()
    db.rollback()
    row = db.get(ContributionEvent, events[0]["event_id"])
    db.delete(row)
    with pytest.raises(ImmutableRecordError):
        db.commit()
    db.rollback()
    db.close()


def test_contribution_rejects_unknown_assets_and_raw_prompt(client, api_key, passport_work):
    base = {"action_type": "MANUAL_EDIT", "description": "Record"}
    response = client.post(
        f"/v1/works/{passport_work}/contributions",
        headers=_headers(api_key),
        json={**base, "output_asset_id": "unknown"},
    )
    assert response.status_code == 404
    response = client.post(
        f"/v1/works/{passport_work}/contributions",
        headers=_headers(api_key),
        json={**base, "prompt_reference": "make this picture look beautiful"},
    )
    assert response.status_code == 422


def test_contribution_integrity_detects_database_tampering(client, api_key, passport_work):
    response = client.post(
        f"/v1/works/{passport_work}/contributions",
        headers=_headers(api_key),
        json={"action_type": "MANUAL_EDIT", "description": "Record"},
    )
    assert response.status_code == 201, response.text
    event_id = response.json()["event_id"]
    # SQLite ORM immutability is separate from verification of externally
    # altered storage; this SQL simulates a damaged database backup.
    from sqlalchemy import text

    with client.app.state.container.database.engine.begin() as connection:
        # Simulate restoring a damaged backup outside the guarded write path.
        # Ordinary SQL updates are rejected by SQLite's immutable-record trigger.
        connection.execute(
            text("DROP TRIGGER IF EXISTS contribution_events_creatorproof_update_guard")
        )
        connection.execute(
            text(
                "UPDATE contribution_events SET human_decision = 'tampered' "
                "WHERE event_id = :event_id"
            ),
            {"event_id": event_id},
        )
    response = client.get(
        f"/v1/works/{passport_work}/contributions/verify", headers=_headers(api_key)
    )
    assert response.json()["valid"] is False
    assert response.json()["broken_sequence"] == 1


def test_public_token_is_hash_only_scoped_redacted_and_revocable(client, api_key, passport_work):
    _create(
        client,
        api_key,
        passport_work,
        {
            "AI_training_permission": "DENY",
            "policy_notes": "private internal note",
            "license_contact": "mailto:secret@example.test",
            "creator_assertion": {"name": "Private Person"},
        },
    )
    issued = client.post(
        f"/v1/works/{passport_work}/verification-token",
        headers=_headers(api_key),
        json={"scopes": ["registration", "rights"]},
    )
    assert issued.status_code == 201, issued.text
    token = issued.json()["token"]
    assert len(token) == 64
    assert issued.headers["cache-control"] == "no-store"
    db = client.app.state.container.database.session_factory()
    row = db.get(PublicVerificationToken, issued.json()["token_id"])
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in repr(row.__dict__)
    db.close()
    verified = client.get(f"/verify/{token}")
    assert verified.status_code == 200, verified.text
    assert verified.json()["public_asset_id"] != passport_work
    assert (
        verified.json()["rights_policy_summary"]["preferences"]["AI_training_permission"] == "DENY"
    )
    for private in [
        passport_work,
        "Private title",
        "owner@example.test",
        "Private Person",
        "secret@example.test",
        "private internal note",
        "tenant_id",
        "storage_key",
    ]:
        assert private not in verified.text
    assert "provenance_status" not in verified.json()
    assert (
        client.delete(
            f"/v1/verification-tokens/{issued.json()['token_id']}", headers=_headers(api_key)
        ).status_code
        == 204
    )
    revoked = client.get(f"/verify/{token}")
    assert revoked.status_code == 410
    assert revoked.json()["detail"]["revoked"] is True


def test_public_token_expiry_invalid_scope_and_unknown_token(client, api_key, passport_work):
    assert (
        client.post(
            f"/v1/works/{passport_work}/verification-token",
            headers=_headers(api_key),
            json={"scopes": ["raw_media"]},
        ).status_code
        == 422
    )
    issued = client.post(
        f"/v1/works/{passport_work}/verification-token",
        headers=_headers(api_key),
        json={"scopes": ["registration"]},
    ).json()
    db = client.app.state.container.database.session_factory()
    row = db.get(PublicVerificationToken, issued["token_id"])
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    db.close()
    assert client.get(f"/verify/{issued['token']}").status_code == 404
    assert client.get("/verify/" + "x" * 64).status_code == 404
    assert client.get("/verify/invalid").status_code == 404


def test_public_scan_evidence_commits_actual_packet_hash_without_private_packet(
    client, api_key, passport_work
):
    container = client.app.state.container
    packet = {
        "schema": "creatorproof.evidence_packet.v1",
        "proof": {"packet_hash_sha256": "d" * 64},
        "provenance": {"status": "VALID_UNTRUSTED"},
        "secret": "raw-model-output",
    }
    db = container.database.session_factory()
    scan = Scan(
        id="scn_public",
        tenant_id=container.settings.dev_tenant_id,
        idempotency_key="public-test",
        catalog_id="passports",
        intended_use="commercial",
        candidate_sha256="e" * 64,
        candidate_phash="0" * 16,
        state="COMPLETED",
        evidence_packet=packet,
        top_match_work_id=passport_work,
    )
    db.add(scan)
    db.commit()
    db.close()
    issued = client.post(
        f"/v1/scans/{scan.id}/verification-token",
        headers=_headers(api_key),
        json={"scopes": ["provenance", "evidence"]},
    ).json()
    response = client.get(f"/verify/{issued['token']}")
    assert response.status_code == 200, response.text
    assert response.json()["packet_hash_sha256"] == "d" * 64
    assert response.json()["provenance_status"] == "VALID_BUT_UNTRUSTED"
    assert "raw-model-output" not in response.text
    assert "rights_policy_summary" not in response.json()


def test_cross_tenant_work_token_policy_and_ledger_are_hidden(client, api_key):
    db = client.app.state.container.database.session_factory()
    db.add(Tenant(id="tenant_other", slug="other", name="Other"))
    db.flush()
    db.add(
        Work(
            id="wrk_other",
            tenant_id="tenant_other",
            catalog_id="other",
            title="Other",
            sha256="f" * 64,
            phash="0" * 16,
            storage_key="other.bin",
        )
    )
    db.commit()
    db.close()
    for suffix in ["rights-policy", "contributions", "contributions/verify"]:
        assert (
            client.get(f"/v1/works/wrk_other/{suffix}", headers=_headers(api_key)).status_code
            == 404
        )
    assert (
        client.post(
            "/v1/works/wrk_other/verification-token", headers=_headers(api_key), json={}
        ).status_code
        == 404
    )


def test_public_lookup_reduces_privileges_to_tenant_after_bootstrap(
    client, api_key, passport_work, monkeypatch
):
    from app.api.routes import passports
    from app.services.tenancy import bind_tenant_context

    bound = []

    def traced_bind(db, tenant_id):
        bind_tenant_context(db, tenant_id)
        bound.append((tenant_id, db.info.copy()))

    monkeypatch.setattr(passports, "bind_tenant_context", traced_bind)
    issued = client.post(
        f"/v1/works/{passport_work}/verification-token", headers=_headers(api_key), json={}
    ).json()
    assert client.get(f"/verify/{issued['token']}").status_code == 200
    assert bound and bound[0][0] == client.app.state.container.settings.dev_tenant_id
    assert bound[0][1]["creatorproof.bypass_rls"] is False


def test_public_verification_issuance_and_access_are_audited(client, api_key, passport_work):
    issued = client.post(
        f"/v1/works/{passport_work}/verification-token", headers=_headers(api_key), json={}
    ).json()
    assert client.get(f"/verify/{issued['token']}").status_code == 200
    db = client.app.state.container.database.session_factory()
    events = db.scalars(select(AuditEvent).where(AuditEvent.resource_id == passport_work)).all()
    assert {row.event_type for row in events} >= {
        "PUBLIC_VERIFICATION_TOKEN_ISSUED",
        "PUBLIC_VERIFICATION_ACCESSED",
    }
    assert issued["token"] not in repr([row.attributes for row in events])
    db.close()


def test_schema_supports_full_passport_fields_without_verified_owner_claim():
    payload = RightsPolicyPayload(
        AI_training_permission="DENY",
        geographic_scope=["us"],
        license_required=True,
        minimum_license_fee="25.50",
        license_fee_currency="USD",
        attribution_required=True,
        attribution_text="Credit creator",
    )
    assert payload.normalized_dimensions()["geographic_scope"] == ["US"]
    assert payload.normalized_dimensions()["minimum_license_fee"] == "25.50"
    assert payload.normalized_permissions()["AI_training_permission"] == "DENY"


@pytest.mark.parametrize("condition", ["channels", "audiences", "transformations"])
def test_export_does_not_erase_non_geographic_conditions(client, api_key, passport_work, condition):
    _create(
        client,
        api_key,
        passport_work,
        {
            **{field: "ALLOW" for field in PERMISSION_FIELDS},
            "dimensions": {condition: ["restricted"], "asset_path": "/photo.png"},
        },
    )
    preferences = client.get(
        f"/v1/works/{passport_work}/ai-preferences", headers=_headers(api_key)
    ).json()
    assert preferences["aipref"]["preferences"] == {}
    ai_txt = client.get(f"/v1/works/{passport_work}/ai.txt", headers=_headers(api_key)).text
    assert "Allow:" not in ai_txt
    tdm = client.get(f"/v1/works/{passport_work}/tdm-policy", headers=_headers(api_key)).json()
    assert tdm["tdm-reservation"] == 1
    assert tdm["tdm-policy"] is None
    assert "tdm-policy" not in tdm["protocol_headers"]


def test_deleted_work_is_hidden_from_passport_ledger_and_public_verification(
    client, api_key, passport_work
):
    issued = client.post(
        f"/v1/works/{passport_work}/verification-token", headers=_headers(api_key), json={}
    ).json()
    db = client.app.state.container.database.session_factory()
    db.get(Work, passport_work).deleted_at = datetime.now(UTC)
    db.commit()
    db.close()
    for suffix in ["rights-policy", "contributions", "contributions/verify"]:
        response = client.get(f"/v1/works/{passport_work}/{suffix}", headers=_headers(api_key))
        assert response.status_code == 404
    assert client.get(f"/verify/{issued['token']}").status_code == 404


def test_resource_writer_can_revoke_own_resource_token_without_rights_write_scope(
    client, api_key, passport_work
):
    from app.api.deps import get_auth
    from app.core.security import AuthContext
    from app.domain.platform import CredentialScope, PrincipalRole

    issued = client.post(
        f"/v1/works/{passport_work}/verification-token", headers=_headers(api_key), json={}
    ).json()
    client.app.dependency_overrides[get_auth] = lambda: AuthContext(
        tenant_id=client.app.state.container.settings.dev_tenant_id,
        auth_method="test",
        role=PrincipalRole.CATALOG_MANAGER,
        scopes=frozenset({CredentialScope.SCANS_WRITE}),
    )
    try:
        assert client.delete(f"/v1/verification-tokens/{issued['token_id']}").status_code == 403
        client.app.dependency_overrides[get_auth] = lambda: AuthContext(
            tenant_id=client.app.state.container.settings.dev_tenant_id,
            auth_method="test",
            role=PrincipalRole.CATALOG_MANAGER,
            scopes=frozenset({CredentialScope.WORKS_WRITE}),
        )
        assert client.delete(f"/v1/verification-tokens/{issued['token_id']}").status_code == 204
    finally:
        client.app.dependency_overrides.pop(get_auth)


def test_public_scan_evidence_rejects_non_hash_private_values(client, api_key):
    container = client.app.state.container
    db = container.database.session_factory()
    scan = Scan(
        id="scan_bad_public_hash",
        tenant_id=container.settings.dev_tenant_id,
        idempotency_key="bad-public-hash",
        catalog_id="passports",
        intended_use="commercial",
        candidate_sha256="e" * 64,
        candidate_phash="0" * 16,
        state="COMPLETED",
        evidence_packet={"proof": {"packet_hash_sha256": "private/person@example.test"}},
    )
    db.add(scan)
    db.commit()
    db.close()
    issued = client.post(
        f"/v1/scans/{scan.id}/verification-token",
        headers=_headers(api_key),
        json={"scopes": ["evidence"]},
    ).json()
    response = client.get(f"/verify/{issued['token']}")
    assert response.status_code == 200
    assert response.json()["packet_hash_sha256"] is None
    assert "person@example.test" not in response.text


def test_issued_public_url_uses_only_configured_origin(client, api_key, passport_work, monkeypatch):
    settings = client.app.state.container.settings
    monkeypatch.setattr(settings, "public_verification_base_url", "https://verify.example.org")
    issued = client.post(
        f"/v1/works/{passport_work}/verification-token",
        headers={**_headers(api_key), "Host": "untrusted.example.org"},
        json={},
    )
    assert issued.status_code == 201, issued.text
    payload = issued.json()
    assert payload["verification_url"] == f"https://verify.example.org/verify/{payload['token']}"
    assert "untrusted.example.org" not in payload["verification_url"]


def test_unconfigured_origin_returns_only_relative_verification_path(
    client, api_key, passport_work, monkeypatch
):
    monkeypatch.setattr(client.app.state.container.settings, "public_verification_base_url", "")
    issued = client.post(
        f"/v1/works/{passport_work}/verification-token", headers=_headers(api_key), json={}
    )
    assert issued.status_code == 201, issued.text
    assert issued.json()["verification_url"] is None
    assert issued.json()["verification_path"].startswith("/verify/")


@pytest.mark.parametrize("kind", ["consent", "revocation"])
def test_future_consent_and_revocation_cannot_be_claimed_as_completed(kind):
    from pydantic import ValidationError

    future = datetime.now(UTC) + timedelta(days=1)
    payload = (
        {"consent_status": "GRANTED", "consent_source": "record", "consent_timestamp": future}
        if kind == "consent"
        else {"revocation_status": "REVOKED", "revocation_timestamp": future}
    )
    with pytest.raises(ValidationError):
        RightsPolicyPayload(**payload)


def test_consent_not_granted_never_becomes_an_export_opt_in(client, api_key, passport_work):
    result = _create(
        client,
        api_key,
        passport_work,
        {"commercial_training_permission": "ALLOW", "consent_status": "NOT_GRANTED"},
    )
    assert result["policy"]["state"] == "CONSENT_NOT_GRANTED"
    tdm = client.get(f"/v1/works/{passport_work}/tdm-policy", headers=_headers(api_key)).json()
    assert tdm["tdm-reservation"] is None


def test_scheduled_future_policy_cannot_allow_use_yet(client, api_key, passport_work):
    result = _create(
        client,
        api_key,
        passport_work,
        {
            "commercial_training_permission": "ALLOW",
            "effective_from": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        },
    )
    assert result["policy"]["state"] == "NOT_YET_EFFECTIVE"
    assert result["exports"]["aipref"]["preferences"] == {}
    tdm = client.get(f"/v1/works/{passport_work}/tdm-policy", headers=_headers(api_key)).json()
    assert tdm["tdm-reservation"] is None


def test_public_scan_rights_remain_bound_to_original_policy_version(client, api_key, passport_work):
    first = _create(client, api_key, passport_work, {"AI_training_permission": "ALLOW"})
    container = client.app.state.container
    db = container.database.session_factory()
    scan = Scan(
        id="scan_pinned_rights",
        tenant_id=container.settings.dev_tenant_id,
        idempotency_key="pinned-rights",
        catalog_id="passports",
        intended_use="AI training",
        candidate_sha256="e" * 64,
        candidate_phash="0" * 16,
        state="COMPLETED",
        top_match_work_id=passport_work,
        evidence_packet={
            "schema": "creatorproof.evidence_packet.v1",
            "proof": {"packet_hash_sha256": "f" * 64},
            "decision": {
                "policy_inputs": {
                    "rights_facts": {
                        "rights_preferences": {
                            "version": first["policy"]["version"],
                            "digest_sha256": first["policy"]["digest_sha256"],
                            "state": "ACTIVE",
                        }
                    }
                }
            },
        },
    )
    db.add(scan)
    db.commit()
    db.close()
    issued = client.post(
        f"/v1/scans/{scan.id}/verification-token", headers=_headers(api_key), json={}
    ).json()
    before = client.get(f"/verify/{issued['token']}").json()
    _create(client, api_key, passport_work, {"AI_training_permission": "DENY"})
    after = client.get(f"/verify/{issued['token']}").json()
    assert before["rights_policy_summary"] == after["rights_policy_summary"]
    assert after["rights_policy_summary"]["policy_version"] == first["policy"]["version"]
    assert after["rights_policy_summary"]["preferences"]["AI_training_permission"] == "ALLOW"
    assert after["rights_policy_summary"]["temporal_binding"] == "AS_OF_SCAN"
    assert after["packet_hash_sha256"] == "f" * 64
    work_token = client.post(
        f"/v1/works/{passport_work}/verification-token", headers=_headers(api_key), json={}
    ).json()
    current = client.get(f"/verify/{work_token['token']}").json()["rights_policy_summary"]
    assert current["policy_version"] == first["policy"]["version"] + 1
    assert current["temporal_binding"] == "CURRENT_WORK_POLICY"


@pytest.mark.parametrize(
    ("payload", "reservation"),
    [
        ({"commercial_training_permission": "ALLOW"}, None),
        ({"dimensions": {"tdm_reservation": 0}}, 0),
        ({"dimensions": {"tdm_reservation": 1}}, 1),
        ({"dimensions": {"tdm_reservation": 0}, "fine_tuning_permission": "DENY"}, 1),
        ({"dimensions": {"tdm_reservation": 0}, "fine_tuning_permission": "REVIEW"}, None),
        ({"dimensions": {"tdm_reservation": 0}, "geographic_scope": ["US"]}, 1),
        (
            {
                "dimensions": {"tdm_reservation": 0},
                "effective_until": datetime.now(UTC) - timedelta(days=1),
            },
            None,
        ),
    ],
)
def test_broad_tdm_nonreservation_requires_explicit_compatible_preference(payload, reservation):
    from types import SimpleNamespace

    from app.services.rights_passport import policy_integrity_projection, tdm_export

    preference = RightsPolicyPayload(**payload)
    row = SimpleNamespace(
        work_id="work",
        version=1,
        permissions=preference.normalized_permissions(),
        dimensions=preference.normalized_dimensions(),
        creator_assertions=preference.assertions(),
        consent_metadata=preference.consent_metadata(),
        revocation_metadata=preference.revocation_metadata(),
        corroboration=[],
        effective_from=preference.effective_from,
        effective_until=preference.effective_until,
    )
    row.digest_sha256 = canonical_digest(policy_integrity_projection(row))
    exported = tdm_export(row, work_id=row.work_id)
    assert exported["tdm-reservation"] == reservation
    assert exported["recorded_tdm_reservation"] == preference.dimensions.tdm_reservation
    assert exported["mapping_reason_codes"]


def test_contribution_does_not_infer_actor_identity_when_omitted():
    from app.api.routes.passports import ContributionPayload

    event = ContributionPayload(action_type="ORIGINAL_SKETCH", description="Caller-recorded step")
    assert event.actor_type == "UNKNOWN"
    assert event.classification == "UNKNOWN"


def test_ai_txt_cannot_erase_explicit_fine_tuning_or_broad_tdm_restrictions():
    from types import SimpleNamespace

    from app.services.rights_passport import ai_txt_export, policy_integrity_projection

    for payload in [
        {
            "AI_training_permission": "ALLOW",
            "commercial_training_permission": "ALLOW",
            "fine_tuning_permission": "DENY",
            "dimensions": {"asset_path": "/photo.png"},
        },
        {
            "AI_training_permission": "ALLOW",
            "commercial_training_permission": "ALLOW",
            "fine_tuning_permission": "ALLOW",
            "dimensions": {"asset_path": "/photo.png", "tdm_reservation": 1},
        },
    ]:
        preference = RightsPolicyPayload(**payload)
        row = SimpleNamespace(
            work_id="work",
            version=1,
            permissions=preference.normalized_permissions(),
            dimensions=preference.normalized_dimensions(),
            creator_assertions=preference.assertions(),
            consent_metadata=preference.consent_metadata(),
            revocation_metadata=preference.revocation_metadata(),
            corroboration=[],
            effective_from=None,
            effective_until=None,
        )
        row.digest_sha256 = canonical_digest(policy_integrity_projection(row))
        assert "Allow:" not in ai_txt_export(row, work_id="work")
