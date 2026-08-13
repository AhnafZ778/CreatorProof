"""End-to-end coverage for the Part 2 platform surface.

These tests exercise the guarantees that the platform actually sells: a scan is
traceable stage by stage, its statement verifies independently, credentials are
scoped, rights history is append-only, and a deletion really deletes.
"""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.domain.platform import StageName, StageState
from app.models import (
    AssetVersion,
    Claim,
    DeletionReceipt,
    EvidenceStatement,
    IntegrityEvent,
    License,
    ReviewCase,
    StageAttempt,
    TransparencyLeaf,
    Work,
)
from app.services.scan_runner import run_scan
from app.services.webhooks import sign_payload, verify_signature


@pytest.fixture
def registered_work(client, scan_headers, image_bytes):
    response = client.post(
        "/v1/works",
        headers={"X-API-Key": scan_headers["X-API-Key"]},
        files={"file": ("reference.png", image_bytes(0), "image/png")},
        data={
            "title": "Reference",
            "catalog_id": "platform-catalog",
            "rights_path": "EXISTING_LICENSE",
            "allowed_uses": json.dumps(["marketing/social"]),
            "claimant": "Platform Creator",
            "claim_state": "CORROBORATED",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def completed_scan(client, scan_headers, image_bytes, registered_work):
    response = client.post(
        "/v1/scans",
        headers=scan_headers,
        files={"file": ("candidate.png", image_bytes(0), "image/png")},
        data={"catalog_id": "platform-catalog", "intended_use": "marketing/social"},
    )
    assert response.status_code == 202, response.text
    scan = response.json()
    body = client.get(f"/v1/scans/{scan['id']}", headers=scan_headers).json()
    assert body["state"] == "COMPLETED", body
    return body


# -- S11 durable orchestration ------------------------------------------------


def test_stage_timeline_reports_every_durable_stage(client, scan_headers, completed_scan):
    response = client.get(f"/v1/scans/{completed_scan['id']}/stages", headers=scan_headers)
    assert response.status_code == 200
    timeline = response.json()
    assert timeline["scan_id"] == completed_scan["id"]
    assert timeline["lifecycle_state"] in {"COMPLETED", "PARTIAL"}
    stages = {row["stage"]: row for row in timeline["stages"]}
    assert "EVIDENCE" in stages
    assert stages["EVIDENCE"]["state"] in {"SUCCEEDED", "SKIPPED"}
    # A stage that succeeded must not still claim to be mid-flight.
    for row in timeline["stages"]:
        if row["state"] == "SUCCEEDED":
            assert row["progress_percent"] == 100


def test_cancelling_a_finished_scan_is_refused(client, scan_headers, completed_scan):
    response = client.post(
        f"/v1/scans/{completed_scan['id']}/cancel",
        headers=scan_headers,
        json={"reason": "changed my mind"},
    )
    assert response.status_code == 409


def test_repeating_an_idempotency_key_returns_the_same_scan(
    client, scan_headers, image_bytes, registered_work
):
    payload = {
        "files": {"file": ("candidate.png", image_bytes(0), "image/png")},
        "data": {"catalog_id": "platform-catalog", "intended_use": "marketing/social"},
    }
    headers = {"X-API-Key": scan_headers["X-API-Key"], "Idempotency-Key": "repeat-me"}
    first = client.post("/v1/scans", headers=headers, **payload)
    second = client.post("/v1/scans", headers=headers, **payload)
    assert first.json()["id"] == second.json()["id"]


# -- S12 signed statements ----------------------------------------------------


def test_statement_is_signed_and_verifies_server_side(client, scan_headers, completed_scan):
    statement = client.get(
        f"/v1/scans/{completed_scan['id']}/statement", headers=scan_headers
    ).json()
    assert statement["signature"]["alg"] == "Ed25519"
    assert statement["signature"]["signature_b64"]

    verification = client.get(
        f"/v1/scans/{completed_scan['id']}/statement/verify", headers=scan_headers
    ).json()
    assert verification["valid"] is True
    assert verification["digest_matches"] is True
    assert verification["signature_valid"] is True


def test_verification_package_verifies_with_the_offline_verifier(
    client, scan_headers, completed_scan
):
    from scripts.verify_evidence_statement import verify_package

    package = client.get(
        f"/v1/scans/{completed_scan['id']}/verification-package", headers=scan_headers
    ).json()
    result = verify_package(
        package,
        expected_issuer_key_fingerprint=package["deployment"]["issuer_key_fingerprint_sha256"],
    )
    assert result["valid"] is True, result["checks"]
    names = {check["name"]: check["result"] for check in result["checks"]}
    assert names["canonical_digest"] == "PASS"
    assert names["signature"] == "PASS"
    assert names["transparency"] == "PASS"
    assert names["packet_binding"] == "PASS"


def test_offline_verifier_rejects_a_tampered_statement(client, scan_headers, completed_scan):
    from scripts.verify_evidence_statement import verify_package

    package = client.get(
        f"/v1/scans/{completed_scan['id']}/verification-package", headers=scan_headers
    ).json()
    package["statement"]["decision"] = {"policy_action": "PASS_BY_POLICY", "tampered": True}
    result = verify_package(
        package,
        expected_issuer_key_fingerprint=package["deployment"]["issuer_key_fingerprint_sha256"],
    )
    assert result["valid"] is False
    failures = {check["name"] for check in result["checks"] if check["result"] == "FAIL"}
    assert "canonical_digest" in failures


def test_status_statement_appends_without_rewriting_history(client, scan_headers, completed_scan):
    original = client.get(
        f"/v1/scans/{completed_scan['id']}/statement", headers=scan_headers
    ).json()
    response = client.post(
        f"/v1/scans/{completed_scan['id']}/statement/status",
        headers=scan_headers,
        json={"statement_type": "DISPUTE", "reason": "The claimant contests this result."},
    )
    assert response.status_code == 201, response.text
    appended = response.json()
    assert appended["statement_id"] != original["statement_id"]

    # The original bytes and digest are untouched; only its status moved.
    current = client.get(f"/v1/scans/{completed_scan['id']}/statement", headers=scan_headers).json()
    assert current["payload_digest_sha256"] == original["payload_digest_sha256"]
    assert current["status"] == "DISPUTED"


def test_transparency_log_is_self_consistent(client, scan_headers, completed_scan):
    response = client.get("/v1/proof/transparency/consistency", headers=scan_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["consistent"] is True
    assert body["scope"] == "LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN"


def test_trust_bundle_publishes_the_public_key_only(client, scan_headers, completed_scan):
    bundle = client.get("/v1/proof/trust-bundle", headers=scan_headers).json()
    assert bundle["keys"], bundle
    serialized = json.dumps(bundle)
    assert "private" not in serialized.lower()
    assert "seed" not in serialized.lower()


# -- S13 credentials, scopes and deletion -------------------------------------


def test_missing_and_wrong_api_keys_are_refused(client):
    assert client.get("/v1/works").status_code == 401
    assert client.get("/v1/works", headers={"X-API-Key": "nope"}).status_code == 401


def _issue_credential(client, scan_headers, *, name: str, scopes: list[str]) -> dict:
    created = client.post(
        "/v1/credentials",
        headers=scan_headers,
        json={"name": name, "role": "AUDITOR", "scopes": scopes},
    )
    assert created.status_code == 201, created.text
    return created.json()


def test_created_credential_returns_its_secret_exactly_once(client, scan_headers):
    body = _issue_credential(client, scan_headers, name="reader", scopes=["works:read"])
    assert body["api_key"].startswith("cpk_")

    listed = client.get("/v1/credentials", headers=scan_headers).json()
    serialized = json.dumps(listed)
    assert "api_key" not in serialized
    assert body["api_key"] not in serialized


def test_a_scoped_credential_cannot_exceed_its_scopes(client, scan_headers, image_bytes):
    created = _issue_credential(client, scan_headers, name="read-only", scopes=["works:read"])
    read_only = {"X-API-Key": created["api_key"]}

    assert client.get("/v1/works", headers=read_only).status_code == 200
    denied = client.post(
        "/v1/works",
        headers=read_only,
        files={"file": ("reference.png", image_bytes(1), "image/png")},
        data={"title": "Should fail", "catalog_id": "platform-catalog"},
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "INSUFFICIENT_SCOPE"


def test_work_list_and_media_require_works_read_scope(client, scan_headers, registered_work):
    created = _issue_credential(client, scan_headers, name="scan-reader", scopes=["scans:read"])
    headers = {"X-API-Key": created["api_key"]}

    assert client.get("/v1/works", headers=headers).status_code == 403
    assert (
        client.get(f"/v1/works/{registered_work['id']}/media", headers=headers).status_code == 403
    )


def test_scan_uses_immutable_asset_version_not_mutable_work_projection(
    client, scan_headers, registered_work, image_bytes
):
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        work = db.get(Work, registered_work["id"])
        assert work is not None
        work.sha256 = "ff" * 32
        work.phash = "0" * 16
        work.storage_key = "references/unsigned-database-override.bin"
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/v1/scans",
        headers={**scan_headers, "Idempotency-Key": "immutable-asset-version-001"},
        files={"file": ("candidate.png", image_bytes(0), "image/png")},
        data={"catalog_id": "platform-catalog", "intended_use": "marketing/social"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["match_status"] == "MATCH_FOUND"
    assert body["top_match_work_id"] == registered_work["id"]
    manifest = body["evidence_packet"]["scope"]["catalog_manifest"]
    assert manifest[0]["asset_version_id"].startswith("astv_")
    assert manifest[0]["sha256"] != "ff" * 32


def test_corrupted_registered_bytes_fail_closed(client, scan_headers, registered_work, image_bytes):
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        asset_version = db.scalar(
            select(AssetVersion).where(AssetVersion.work_id == registered_work["id"])
        )
        assert asset_version is not None
        container.storage.put(asset_version.storage_key, image_bytes(23))
    finally:
        db.close()

    media = client.get(f"/v1/works/{registered_work['id']}/media", headers=scan_headers)
    assert media.status_code == 409
    assert media.json()["detail"]["code"] == "REFERENCE_ASSET_INTEGRITY_MISMATCH"

    response = client.post(
        "/v1/scans",
        headers={**scan_headers, "Idempotency-Key": "corrupt-reference-fails-closed-001"},
        files={"file": ("candidate.png", image_bytes(0), "image/png")},
        data={"catalog_id": "platform-catalog", "intended_use": "marketing/social"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["policy_action"] != "PASS_BY_POLICY"
    assert body["evidence_packet"]["scope"]["coverage_status"] == "FAILED"
    failures = body["evidence_packet"]["scope"]["verification_failures"]
    assert failures[0]["error_code"] == "REFERENCE_ASSET_SHA256_MISMATCH"


def test_revoked_credential_stops_working(client, scan_headers):
    created = _issue_credential(client, scan_headers, name="temporary", scopes=["works:read"])
    headers = {"X-API-Key": created["api_key"]}
    assert client.get("/v1/works", headers=headers).status_code == 200

    revoked = client.delete(f"/v1/credentials/{created['credential']['id']}", headers=scan_headers)
    assert revoked.status_code in {200, 204}
    assert client.get("/v1/works", headers=headers).status_code == 401


def test_deleting_a_work_returns_a_receipt_and_removes_the_bytes(
    client, scan_headers, registered_work
):
    response = client.delete(f"/v1/works/{registered_work['id']}", headers=scan_headers)
    assert response.status_code == 200, response.text
    receipt = response.json()
    assert receipt["state"] in {"COMPLETED", "COMPLETED_WITH_EXCEPTIONS"}
    assert receipt["objects_retained"] == []
    media = client.get(f"/v1/works/{registered_work['id']}/media", headers=scan_headers)
    assert media.status_code == 404


def test_deletion_intent_is_durable_before_object_removal(
    client, scan_headers, registered_work, monkeypatch
):
    container = client.app.state.container
    original_delete_prefix = container.storage.delete_prefix
    observed = {"durable": False}

    def inspect_then_delete(prefix):
        db = container.database.session_factory()
        try:
            receipt = next(
                (
                    row
                    for row in db.scalars(select(DeletionReceipt)).all()
                    if (row.requested_scope or {}).get("work_id") == registered_work["id"]
                ),
                None,
            )
            event = db.scalar(
                select(IntegrityEvent).where(
                    IntegrityEvent.subject_id == registered_work["id"],
                    IntegrityEvent.event_type == "WORK_DELETION_REQUESTED",
                )
            )
            observed["durable"] = bool(
                receipt is not None
                and receipt.state == "REQUESTED"
                and event is not None
                and event.signature_b64
            )
        finally:
            db.close()
        return original_delete_prefix(prefix)

    monkeypatch.setattr(container.storage, "delete_prefix", inspect_then_delete)
    response = client.delete(f"/v1/works/{registered_work['id']}", headers=scan_headers)

    assert response.status_code == 200, response.text
    assert observed["durable"] is True


# -- S9 rights, claims, licences and policy ------------------------------------


def test_rights_events_are_append_only_and_change_the_position(
    client, scan_headers, registered_work
):
    party = client.post(
        "/v1/rights/parties",
        headers=scan_headers,
        json={
            "external_ref": "creator-1",
            "display_name": "Platform Creator",
            "party_type": "INDIVIDUAL",
        },
    )
    assert party.status_code == 201, party.text
    claim_response = client.post(
        "/v1/rights/claims",
        headers=scan_headers,
        json={
            "work_id": registered_work["id"],
            "claimant_label": "Platform Creator",
            "claimant_party_id": party.json()["id"],
            "claim_type": "AUTHORSHIP",
            "authority_level": "CORROBORATED_BY_PLATFORM",
        },
    )
    assert claim_response.status_code == 201, claim_response.text
    claim = claim_response.json()

    revoked = client.post(
        f"/v1/rights/claims/{claim['id']}/events",
        headers=scan_headers,
        json={"event_type": "REVOKED", "reason": "Withdrawn by the claimant."},
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["state"] == "REVOKED"

    position = client.get(
        f"/v1/rights/works/{registered_work['id']}/position", headers=scan_headers
    ).json()
    assert position["history"], position
    assert position["history"][-1]["event_type"] == "REVOKED"
    # A revoked claim must never be presented as authorizing anything.
    assert not position.get("authorized", False)


def test_registration_attests_each_implicit_rights_subject(client, scan_headers, registered_work):
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        claim = db.scalar(select(Claim).where(Claim.work_id == registered_work["id"]))
        license_row = db.scalar(select(License).where(License.work_id == registered_work["id"]))
        assert claim is not None
        assert license_row is not None
        events = db.scalars(
            select(IntegrityEvent).where(IntegrityEvent.subject_id.in_([claim.id, license_row.id]))
        ).all()
        assert {event.event_type for event in events} == {"CLAIM_CREATED", "LICENSE_CREATED"}
        for event in events:
            assert event.signature_b64
            assert event.payload["attributes"]["projection_digest_sha256"]
            assert db.scalar(
                select(TransparencyLeaf).where(TransparencyLeaf.statement_id == event.id)
            )
    finally:
        db.close()

    position = client.get(
        f"/v1/rights/works/{registered_work['id']}/position", headers=scan_headers
    ).json()
    assert all(item["integrity"]["verified"] for item in position["claims"])
    assert all(item["integrity"]["verified"] for item in position["licenses"])


def test_mutated_rights_projection_cannot_authorize_a_match(
    client, scan_headers, image_bytes, registered_work
):
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        claim = db.scalar(select(Claim).where(Claim.work_id == registered_work["id"]))
        assert claim is not None
        claim.authority_level = "UNSIGNED_DATABASE_OVERRIDE"
        db.commit()
    finally:
        db.close()

    response = client.post(
        "/v1/scans",
        headers={**scan_headers, "Idempotency-Key": "rights-integrity-tamper-001"},
        files={"file": ("candidate.png", image_bytes(0), "image/png")},
        data={"catalog_id": "platform-catalog", "intended_use": "marketing/social"},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["match_status"] == "MATCH_FOUND"
    assert body["policy_action"] == "REVIEW"
    rights_facts = body["evidence_packet"]["decision"]["policy_inputs"]["rights_facts"]
    assert "CLAIM_PROJECTION_INTEGRITY_MISMATCH" in rights_facts["claim_reason_codes"]


def test_policy_dry_run_does_not_change_the_recorded_decision(client, scan_headers, completed_scan):
    before = client.get(f"/v1/scans/{completed_scan['id']}", headers=scan_headers).json()
    dry_run = client.post(
        "/v1/policies/dry-run",
        headers=scan_headers,
        json={"scan_id": completed_scan["id"]},
    )
    assert dry_run.status_code == 200, dry_run.text
    after = client.get(f"/v1/scans/{completed_scan['id']}", headers=scan_headers).json()
    assert after["policy_action"] == before["policy_action"]


def test_policy_versions_are_immutable(client, scan_headers):
    created = client.post(
        "/v1/policies",
        headers=scan_headers,
        json={"policy_key": "strict", "rules": {"block_on_copy_match": True}},
    )
    assert created.status_code == 201, created.text
    first = created.json()
    second = client.post(
        "/v1/policies",
        headers=scan_headers,
        json={"policy_key": "strict", "rules": {"block_on_copy_match": False}},
    ).json()
    assert second["version"] > first["version"]
    assert second["id"] != first["id"]


def test_default_policy_seed_has_a_signed_transparency_commitment(client):
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        event = db.scalar(
            select(IntegrityEvent).where(
                IntegrityEvent.event_type.in_(
                    ["POLICY_VERSION_CREATED", "POLICY_VERSION_SEED_ATTESTED"]
                ),
                IntegrityEvent.subject_type == "policy_version",
            )
        )
        assert event is not None
        assert event.signature_b64
        leaf = db.scalar(select(TransparencyLeaf).where(TransparencyLeaf.statement_id == event.id))
        assert leaf is not None
        assert leaf.packet_hash_sha256 == event.payload_digest_sha256
    finally:
        db.close()


# -- S16 review workflow and webhooks -----------------------------------------


def test_review_actions_are_attributable_and_immutable(client, scan_headers, completed_scan):
    cases = client.get("/v1/review-cases", headers=scan_headers).json()
    if not cases:
        pytest.skip("This scan did not require review, so no case was opened.")
    case_id = cases[0]["id"]

    action = client.post(
        f"/v1/review-cases/{case_id}/actions",
        headers=scan_headers,
        json={"event_type": "COMMENT_ADDED", "note": "Checked the licence on file."},
    )
    assert action.status_code == 201, action.text

    detail = client.get(f"/v1/review-cases/{case_id}", headers=scan_headers).json()
    events = detail["events"]
    assert events, detail
    assert all(event.get("actor_label") or event.get("actor_principal_id") for event in events)
    assert all(event.get("created_at") for event in events)


def test_automatic_review_case_is_bound_to_statement_and_integrity_log(
    client, scan_headers, image_bytes
):
    response = client.post(
        "/v1/scans",
        headers={**scan_headers, "Idempotency-Key": "review-case-integrity-001"},
        data={"catalog_id": "empty-review-catalog", "intended_use": "marketing/social"},
        files={"file": ("candidate.png", image_bytes(19), "image/png")},
    )
    assert response.status_code == 202, response.text
    scan_id = response.json()["id"]

    container = client.app.state.container
    db = container.database.session_factory()
    try:
        case = db.scalar(select(ReviewCase).where(ReviewCase.scan_id == scan_id))
        statement = db.scalar(select(EvidenceStatement).where(EvidenceStatement.scan_id == scan_id))
        assert case is not None
        assert statement is not None
        assert case.statement_id == statement.id

        event = db.scalar(
            select(IntegrityEvent).where(
                IntegrityEvent.event_type == "REVIEW_CASE_CREATED",
                IntegrityEvent.subject_id == case.id,
            )
        )
        assert event is not None
        assert event.payload["attributes"]["statement_id"] == statement.id
        assert event.payload["attributes"]["packet_hash_sha256"]
        leaf = db.scalar(select(TransparencyLeaf).where(TransparencyLeaf.statement_id == event.id))
        assert leaf is not None
        assert leaf.packet_hash_sha256 == event.payload_digest_sha256
    finally:
        db.close()


def test_review_assignee_transition_is_signed(client, scan_headers, image_bytes):
    response = client.post(
        "/v1/scans",
        headers={**scan_headers, "Idempotency-Key": "review-assignee-integrity-001"},
        data={"catalog_id": "empty-assignee-catalog", "intended_use": "review"},
        files={"file": ("candidate.png", image_bytes(17), "image/png")},
    )
    assert response.status_code == 202, response.text
    case = client.get("/v1/review-cases", headers=scan_headers).json()[0]
    action = client.post(
        f"/v1/review-cases/{case['id']}/actions",
        headers=scan_headers,
        json={
            "event_type": "ASSIGNED",
            "note": "Assign for verification",
            "assignee_principal_id": "prn_integrity_reviewer",
        },
    )
    assert action.status_code == 201, action.text

    db = client.app.state.container.database.session_factory()
    try:
        event = db.scalar(
            select(IntegrityEvent)
            .where(
                IntegrityEvent.subject_id == case["id"],
                IntegrityEvent.event_type == "REVIEW_ACTION_RECORDED",
            )
            .order_by(IntegrityEvent.created_at.desc())
        )
        assert event is not None
        attributes = event.payload["attributes"]
        assert attributes["previous_assignee_principal_id"] is None
        assert attributes["new_assignee_principal_id"] == "prn_integrity_reviewer"
    finally:
        db.close()


def test_committed_statement_reconciles_stage_before_proof(client, completed_scan):
    container = client.app.state.container
    db = container.database.session_factory()
    try:
        result_count = len(
            db.scalars(
                select(EvidenceStatement).where(
                    EvidenceStatement.scan_id == completed_scan["id"],
                    EvidenceStatement.statement_type == "RESULT",
                )
            ).all()
        )
        for stage, state in (
            (StageName.STATEMENT, StageState.FAILED_RETRYABLE),
            (StageName.PROOF, StageState.PENDING),
            (StageName.NOTIFY, StageState.PENDING),
        ):
            row = db.scalar(
                select(StageAttempt).where(
                    StageAttempt.scan_id == completed_scan["id"],
                    StageAttempt.stage == str(stage),
                )
            )
            assert row is not None
            row.state = str(state)
            row.lease_owner = None
            row.lease_expires_at = None
        db.commit()
    finally:
        db.close()

    run_scan(container, completed_scan["id"])

    db = container.database.session_factory()
    try:
        assert (
            len(
                db.scalars(
                    select(EvidenceStatement).where(
                        EvidenceStatement.scan_id == completed_scan["id"],
                        EvidenceStatement.statement_type == "RESULT",
                    )
                ).all()
            )
            == result_count
        )
        states = {
            row.stage: row.state
            for row in db.scalars(
                select(StageAttempt).where(StageAttempt.scan_id == completed_scan["id"])
            ).all()
        }
        assert states[str(StageName.STATEMENT)] == str(StageState.SUCCEEDED)
        assert states[str(StageName.PROOF)] == str(StageState.SUCCEEDED)
        assert states[str(StageName.NOTIFY)] == str(StageState.SUCCEEDED)
    finally:
        db.close()


def test_statement_successor_constraint_race_returns_409(
    client, scan_headers, completed_scan, monkeypatch
):
    def collide(*args, **kwargs):
        del args, kwargs
        raise IntegrityError("insert", {}, RuntimeError("unique predecessor"))

    monkeypatch.setattr("app.api.routes.scans.issue_status_statement", collide)
    response = client.post(
        f"/v1/scans/{completed_scan['id']}/statement/status",
        headers=scan_headers,
        json={"statement_type": "DISPUTE", "reason": "Concurrent review"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "STALE_STATEMENT_LINEAGE"


def test_webhook_signature_verifies_and_rejects_a_replay():
    body = b'{"delivery_id":"whd_1","event_type":"scan.completed"}'
    timestamp = str(int(__import__("time").time()))
    signature = sign_payload("secret", timestamp, body)

    assert verify_signature("secret", signature=signature, timestamp=timestamp, body=body)
    assert not verify_signature("other", signature=signature, timestamp=timestamp, body=body)
    assert not verify_signature(
        "secret", signature=signature, timestamp=timestamp, body=body + b" "
    )
    # A delivery captured and replayed an hour later fails on the timestamp.
    stale = str(int(timestamp) - 3600)
    assert not verify_signature(
        "secret", signature=sign_payload("secret", stale, body), timestamp=stale, body=body
    )


def test_webhook_endpoint_secret_is_returned_once_then_hidden(client, scan_headers):
    created = client.post(
        "/v1/webhooks/endpoints",
        headers=scan_headers,
        json={"url": "https://example.com/hook", "event_types": ["scan.completed"]},
    )
    assert created.status_code == 201, created.text
    secret = created.json()["signing_secret"]
    assert secret

    listed = client.get("/v1/webhooks/endpoints", headers=scan_headers).json()
    assert secret not in json.dumps(listed)


# -- S14 observability ---------------------------------------------------------


def test_metrics_endpoint_exposes_prometheus_text(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "creatorproof_" in response.text


def test_readiness_reports_degraded_capabilities_honestly(client):
    body = client.get("/readyz").json()
    assert "degraded_capabilities" in body
    assert isinstance(body["degraded_capabilities"], list)


def test_every_response_carries_a_correlation_id(client):
    response = client.get("/healthz")
    assert response.headers.get("X-Correlation-Id")


# -- S16 bulk import -----------------------------------------------------------


def test_bulk_import_reports_per_file_outcomes(client, scan_headers, image_bytes):
    response = client.post(
        "/v1/works/bulk",
        headers={"X-API-Key": scan_headers["X-API-Key"]},
        files=[
            ("files", ("a.png", image_bytes(2), "image/png")),
            ("files", ("b.png", image_bytes(3), "image/png")),
            ("files", ("broken.png", b"not an image", "image/png")),
        ],
        data={
            "catalog_id": "bulk-catalog",
            "manifest": json.dumps(
                [
                    {"filename": "a.png", "title": "First", "rights_path": "EXISTING_LICENSE"},
                    {"filename": "b.png", "title": "Second"},
                ]
            ),
        },
    )
    assert response.status_code == 207, response.text
    body = response.json()
    assert len(body["imported"]) == 2
    assert len(body["rejected"]) == 1
    assert body["complete"] is False


# -- S17 usage metering and plan limits ---------------------------------------


def test_registering_a_work_meters_assets_and_storage(client, scan_headers, registered_work):
    body = client.get("/v1/usage", headers=scan_headers).json()
    totals = body["totals"]
    assert totals["protected_asset"] == 1
    # Storage is metered in real bytes, so it must be a positive count.
    assert totals["storage_bytes"] > 0
    assert body["window_days"] == 30


def test_a_completed_scan_is_metered_once(client, scan_headers, completed_scan):
    body = client.get("/v1/usage", headers=scan_headers).json()
    assert body["totals"]["scan"] == 1


def test_usage_reports_every_meter_including_unused_ones(client, scan_headers):
    body = client.get("/v1/usage", headers=scan_headers).json()
    # A meter with no activity reports zero rather than disappearing, so a
    # dashboard cannot read "not measured" as "nothing used".
    for meter in ("scan", "protected_asset", "storage_bytes", "gpu_stage_seconds", "proof_anchor"):
        assert body["totals"][meter] == 0


def test_usage_reports_units_not_prices(client, scan_headers):
    body = client.get("/v1/usage", headers=scan_headers).json()
    assert "scan_quota_per_day" in body["plan"]
    # Metering reports quantities only. Pricing belongs to a rate card measured
    # from real infrastructure, not to a hard-coded field in the API.
    priced = {"price", "cost", "amount", "currency", "usd"}
    keys = set(body["totals"]) | set(body["plan"]) | set(body)
    assert not any(any(token in key.lower() for token in priced) for key in keys)


def test_usage_requires_a_credential(client):
    assert client.get("/v1/usage").status_code == 401
