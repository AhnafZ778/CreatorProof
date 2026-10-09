"""End-to-end scope authorization and media lifetime, beyond helper-only tests."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.domain.enums import ScanState
from app.models import DeletionReceipt, EvidenceMatrix, ProvenanceRecord, Scan, ScanInputBinding
from app.services.orchestration import ScanCancelled
from app.services.retention import purge_candidate_media, purge_expired_candidates


def _register(client, headers, raw):
    response = client.post(
        "/v1/works",
        headers=headers,
        data={"catalog_id": "scope-test", "title": "Owned fixture"},
        files={"file": ("original.png", raw, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _scan(client, headers, raw, *, key, context=None, country=None):
    data = {"catalog_id": "scope-test", "intended_use": "editorial"}
    if context is not None:
        data["use_context"] = json.dumps(context)
    if country is not None:
        data["country_code"] = country
    return client.post(
        "/v1/scans",
        headers={**headers, "Idempotency-Key": key},
        data=data,
        files={"file": ("candidate.png", raw, "image/png")},
    )


@pytest.mark.parametrize(
    "context,expected",
    [
        ({"territory": "us", "channel": "web"}, "PASS_BY_POLICY"),
        ({"territory": "DE", "channel": "web"}, "REVIEW"),
        ({"territory": "US", "channel": "print"}, "REVIEW"),
        (None, "REVIEW"),
    ],
)
def test_scan_applies_license_dimensions(client, api_key, image_bytes, context, expected):
    headers = {"X-API-Key": api_key}
    raw = image_bytes()
    work_id = _register(client, headers, raw)
    claim = client.post(
        "/v1/rights/claims",
        headers=headers,
        json={"work_id": work_id, "claimant_label": "Test fixture creator"},
    )
    assert claim.status_code == 201, claim.text
    review = client.post(
        f"/v1/rights/claims/{claim.json()['id']}/events",
        headers=headers,
        json={"event_type": "CORROBORATED", "reason": "Recorded fixture evidence"},
    )
    assert review.status_code in {200, 201}, review.text
    license_response = client.post(
        "/v1/rights/licenses",
        headers=headers,
        json={
            "work_id": work_id,
            "claim_id": claim.json()["id"],
            "permitted_uses": ["editorial"],
            "territories": ["US"],
            "channels": ["web"],
        },
    )
    assert license_response.status_code == 201, license_response.text
    result = _scan(client, headers, raw, key="scope-dimensions-1", context=context)
    assert result.status_code == 202, result.text
    assert result.json()["match_status"] == "MATCH_FOUND"
    assert result.json()["policy_action"] == expected, result.json()["reason_codes"]
    facts = result.json()["evidence_packet"]["decision"]["policy_inputs"]["rights_facts"]
    assert facts["scope_context"] == (
        {**context, "territory": context["territory"].upper()} if context else {}
    )


def test_context_and_submission_country_are_idempotency_bound(client, api_key, image_bytes):
    headers = {"X-API-Key": api_key}
    raw = image_bytes()
    _register(client, headers, raw)
    first = _scan(
        client, headers, raw, key="scope-idempotency-1", context={"territory": "US"}, country="BD"
    )
    replay = _scan(
        client, headers, raw, key="scope-idempotency-1", context={"territory": "us"}, country="bd"
    )
    assert first.status_code == replay.status_code == 202
    assert first.json()["id"] == replay.json()["id"]
    for context, country in [({"territory": "DE"}, "BD"), ({"territory": "US"}, "US")]:
        conflict = _scan(
            client, headers, raw, key="scope-idempotency-1", context=context, country=country
        )
        assert conflict.status_code == 409, conflict.text
    with client.app.state.container.database.session_factory() as db:
        binding = db.scalar(
            select(ScanInputBinding).where(ScanInputBinding.scan_id == first.json()["id"])
        )
        assert first.json()["request_digest"] == binding.request_digest
        assert binding.requested_capabilities["submission_country_code"] == "BD"
        assert binding.requested_capabilities["use_context"] == {"territory": "US"}


@pytest.mark.parametrize(
    "context",
    [
        {"territory": "127.0.0.1"},
        {"unknown": "value"},
        {"model": "bad\nmodel"},
        {"rights_permission": "own_everything"},
    ],
)
def test_invalid_context_rejected_before_scan_creation(client, api_key, image_bytes, context):
    result = _scan(
        client, {"X-API-Key": api_key}, image_bytes(), key="scope-invalid-1", context=context
    )
    assert result.status_code == 422, result.text
    with client.app.state.container.database.session_factory() as db:
        assert db.scalar(select(Scan)) is None


def test_positive_retention_expires_media_but_preserves_evidence(client, api_key, image_bytes):
    container = client.app.state.container
    container.settings.candidate_retention_seconds = 60
    headers = {"X-API-Key": api_key}
    raw = image_bytes()
    _register(client, headers, raw)
    result = _scan(client, headers, raw, key="retention-positive-1")
    assert result.status_code == 202, result.text
    scan_id = result.json()["id"]
    assert client.get(f"/v1/scans/{scan_id}/media", headers=headers).status_code == 200
    assert purge_expired_candidates(container) == 0
    with container.database.session_factory() as db:
        scan = db.get(Scan, scan_id)
        scan.completed_at = datetime.now(UTC) - timedelta(seconds=61)
        storage_key = scan.candidate_storage_key
        db.commit()
    # Read access enforces expiry even before the next background sweep.
    assert client.get(f"/v1/scans/{scan_id}/media", headers=headers).status_code == 404
    with pytest.raises(FileNotFoundError):
        container.storage.read(storage_key)
    with container.database.session_factory() as db:
        assert db.get(Scan, scan_id).candidate_storage_key is None
        assert db.scalar(select(EvidenceMatrix).where(EvidenceMatrix.scan_id == scan_id))
        assert db.scalar(select(ProvenanceRecord).where(ProvenanceRecord.scan_id == scan_id))
        assert db.scalar(select(DeletionReceipt).where(DeletionReceipt.state == "COMPLETED"))
    assert purge_expired_candidates(container) == 0


def test_failed_deletion_is_retried_without_discarding_locator(
    client,
    api_key,
    image_bytes,
    monkeypatch,
):
    container = client.app.state.container
    container.settings.candidate_retention_seconds = 60
    headers = {"X-API-Key": api_key}
    result = _scan(client, headers, image_bytes(), key="retention-retry-1")
    assert result.status_code == 202, result.text
    scan_id = result.json()["id"]
    original = container.storage.delete_prefix

    def unavailable(_prefix):
        raise OSError("storage unavailable")

    monkeypatch.setattr(container.storage, "delete_prefix", unavailable)
    with container.database.session_factory() as db:
        scan = db.get(Scan, scan_id)
        key = scan.candidate_storage_key
        assert not purge_candidate_media(container, db, scan, force=True)
        assert scan.candidate_storage_key == key
        assert db.scalar(select(DeletionReceipt).where(DeletionReceipt.state == "FAILED"))
    monkeypatch.setattr(container.storage, "delete_prefix", original)
    with container.database.session_factory() as db:
        scan = db.get(Scan, scan_id)
        assert purge_candidate_media(container, db, scan, force=True)
        assert scan.candidate_storage_key is None
        assert db.scalar(select(DeletionReceipt).where(DeletionReceipt.state == "COMPLETED"))
    with pytest.raises(FileNotFoundError):
        container.storage.read(key)


def test_retention_never_deletes_running_candidate(client, api_key, image_bytes):
    container = client.app.state.container
    container.settings.candidate_retention_seconds = 60
    response = _scan(client, {"X-API-Key": api_key}, image_bytes(), key="retention-running-1")
    assert response.status_code == 202, response.text
    with container.database.session_factory() as db:
        scan = db.get(Scan, response.json()["id"])
        scan.state = ScanState.PROCESSING
        scan.completed_at = None
        scan.created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()
        assert not purge_candidate_media(container, db, scan)
        assert container.storage.read(scan.candidate_storage_key)


@pytest.mark.parametrize(
    "failure", [ValueError("invalid evidence"), ScanCancelled("SCAN_CANCELLED_BY_REQUEST")]
)
def test_terminal_failure_persists_abstention_and_releases_media(
    client,
    api_key,
    image_bytes,
    monkeypatch,
    failure,
):
    import app.services.evidence as evidence

    def fail_stage(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(evidence, "build_evidence_packet", fail_stage)
    headers = {"X-API-Key": api_key}
    result = _scan(client, headers, image_bytes(), key="terminal-matrix-1")
    assert result.status_code == 202, result.text
    body = result.json()
    assert body["state"] == "FAILED"
    assert body["policy_action"] == "REVIEW"
    assert body["evidence_packet"]["schema"] == "creatorproof.failure-evidence.v1"
    matrix = client.get(f"/v1/scans/{body['id']}/evidence-matrix", headers=headers)
    assert matrix.status_code == 200, matrix.text
    assert matrix.json()["final_status"] == "PROVIDER_FAILURE"
    assert matrix.json()["abstention"] is True
    assert matrix.json()["legal_conclusion"] is None
    assert len(matrix.json()["signals"]) == 8
    assert all(not signal["artifact_refs"] for signal in matrix.json()["signals"])
    assert client.get(f"/v1/scans/{body['id']}/media", headers=headers).status_code == 404
    with client.app.state.container.database.session_factory() as db:
        assert db.get(Scan, body["id"]).candidate_storage_key is None
