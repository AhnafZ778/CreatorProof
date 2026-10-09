"""Durable scan-to-admin handoff, evidence context, and copyright draft boundaries."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import generate_api_key
from app.models import ApiCredential, Scan, Tenant, new_id
from app.services.aiand import AiAndClient


def _headers(api_key):
    return {"X-API-Key": api_key}


def _seed_scan(
    client,
    *,
    packet=None,
    action="PASS_BY_POLICY",
    match="NO_MATCH_IN_CHECKED_SOURCES",
    state="COMPLETED",
    tenant_id=None,
    when=None,
):
    container = client.app.state.container
    tenant_id = tenant_id or container.settings.dev_tenant_id
    scan_id = new_id("scn")
    with container.database.session_factory() as db:
        db.add(
            Scan(
                id=scan_id,
                tenant_id=tenant_id,
                idempotency_key=scan_id,
                catalog_id="flag-test",
                intended_use="editorial",
                candidate_sha256="a" * 64,
                candidate_phash="0" * 16,
                state=state,
                match_status=match,
                policy_action=action,
                evidence_packet=packet or {},
                created_at=when or datetime.now(UTC),
                completed_at=when or datetime.now(UTC),
            )
        )
        db.commit()
    return scan_id


def _notice_payload(scan_id):
    return {
        "scan_id": scan_id,
        "jurisdiction": "US",
        "claimant_name": "Registered claimant",
        "claimant_email": "claimant@example.com",
        "protected_title": "Operator description",
        "protected_url": "https://artist.example/original",
        "evidence_summary": "Compare the retained registration and the submitted image.",
    }


@pytest.mark.parametrize(
    "packet,action,match,category,reason,classification",
    [
        (
            {"synthetic_origin": {"classification": "LIKELY_AI_GENERATED"}},
            "PASS_BY_POLICY",
            "NO_MATCH_IN_CHECKED_SOURCES",
            "CONTENT_FLAG",
            "AI_ORIGIN_INDICATORS",
            "AI_GENERATED",
        ),
        (
            {"synthetic_origin": {"classification": "AI_ORIGIN_REVIEW_CANDIDATE"}},
            "PASS_BY_POLICY",
            "NO_MATCH_IN_CHECKED_SOURCES",
            "CONTENT_FLAG",
            "AI_ORIGIN_INDICATORS",
            "AI_GENERATED",
        ),
        (
            {
                "style_analysis": {
                    "learned_provider_active": True,
                    "decision": {"review_recommended": True},
                }
            },
            "PASS_BY_POLICY",
            "NO_MATCH_IN_CHECKED_SOURCES",
            "CONTENT_FLAG",
            "CREATOR_RESEMBLANCE",
            "UNCLASSIFIED",
        ),
        (
            {
                "synthetic_origin": {"classification": "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"},
            },
            "REVIEW",
            "SCOPE_INCOMPLETE",
            "ASSESSMENT_GAP",
            "POLICY_REVIEW",
            "UNCLASSIFIED",
        ),
        ({}, "BLOCK", "INCONCLUSIVE", "CONTENT_FLAG", "COPY_EVIDENCE_INCONCLUSIVE", "UNCLASSIFIED"),
    ],
)
def test_non_match_flags_reach_admin_with_review_only_evidence(
    client, api_key, packet, action, match, category, reason, classification
):
    scan_id = _seed_scan(client, packet=packet, action=action, match=match)
    headers = _headers(api_key)
    result = client.get("/v1/admin/user-detections", headers=headers)
    assert result.status_code == 200, result.text
    [detection] = result.json()
    assert detection["scan_id"] == scan_id
    assert detection["category"] == category
    assert reason in detection["flag_reasons"]
    assert detection["classification"] == classification
    assert detection["matched_work"] is None
    assert detection["takedown_eligible"] is False
    assert detection["takedown_block_reason"]
    scan = client.get(f"/v1/scans/{scan_id}", headers=headers).json()
    assert scan["admin_review"]["status"] == "needs_review"
    assert scan["admin_review"]["category"] == category
    assert scan["admin_review"]["reasons"] == detection["flag_reasons"]
    created = client.post(f"/v1/admin/user-detections/{scan_id}/review-case", headers=headers)
    replay = client.post(f"/v1/admin/user-detections/{scan_id}/review-case", headers=headers)
    assert created.status_code == replay.status_code == 200
    assert created.json()["id"] == replay.json()["id"]
    assert created.json()["state"] == "OPEN"
    rejected = client.post(
        "/v1/admin/takedowns/drafts", headers=headers, json=_notice_payload(scan_id)
    )
    assert rejected.status_code == 409


@pytest.mark.parametrize(
    "packet,state,action",
    [
        (
            {"synthetic_origin": {"classification": "NO_AI_ORIGIN_EVIDENCE_DETECTED"}},
            "COMPLETED",
            "PASS_BY_POLICY",
        ),
        (
            {
                "synthetic_origin": {
                    "classification": "AI_ORIGIN_UNKNOWN",
                    "scorecard": {"signal_score": 99},
                }
            },
            "COMPLETED",
            "PASS_BY_POLICY",
        ),
        (
            {
                "style_analysis": {
                    "learned_provider_active": False,
                    "decision": {"review_recommended": True},
                }
            },
            "COMPLETED",
            "PASS_BY_POLICY",
        ),
        ({"synthetic_origin": {"classification": "LIKELY_AI_GENERATED"}}, "FAILED", "REVIEW"),
        ({"synthetic_origin": {"classification": "LIKELY_AI_GENERATED"}}, "PROCESSING", "REVIEW"),
    ],
)
def test_clean_unmeasured_and_unfinished_results_do_not_become_content_flags(
    client, api_key, packet, state, action
):
    scan_id = _seed_scan(client, packet=packet, state=state, action=action)
    headers = _headers(api_key)
    response = client.get("/v1/admin/user-detections", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json() == []
    scan = client.get(f"/v1/scans/{scan_id}", headers=headers).json()
    assert scan["admin_review"]["status"] != "needs_review"
    review = client.post(f"/v1/admin/user-detections/{scan_id}/review-case", headers=headers)
    assert review.status_code == 409


def test_flag_pagination_excludes_clean_rows_before_limiting_and_is_tenant_scoped(client, api_key):
    container = client.app.state.container
    old = datetime.now(UTC) - timedelta(days=1)
    flag_id = _seed_scan(client, action="REVIEW", match="INCONCLUSIVE", when=old)
    for _ in range(3):
        _seed_scan(client)
    with container.database.session_factory() as db:
        db.add(Tenant(id="tn_other_flags", slug="other-flags", name="Other tenant"))
        db.commit()
    other = _seed_scan(client, tenant_id="tn_other_flags", action="BLOCK", match="MATCH_FOUND")
    headers = _headers(api_key)
    response = client.get("/v1/admin/user-detections?limit=1", headers=headers)
    assert [row["scan_id"] for row in response.json()] == [flag_id]
    assert client.get("/v1/admin/user-detections?limit=1&offset=1", headers=headers).json() == []
    exact = client.get(f"/v1/admin/user-detections?scan_id={flag_id}", headers=headers)
    assert exact.json()[0]["scan_id"] == flag_id
    assert client.get(f"/v1/admin/user-detections?scan_id={other}", headers=headers).json() == []
    assert (
        client.post(f"/v1/admin/user-detections/{other}/review-case", headers=headers).status_code
        == 404
    )
    assert (
        client.post(
            "/v1/admin/takedowns/drafts", headers=headers, json=_notice_payload(other)
        ).status_code
        == 404
    )


def test_matched_upload_persists_source_country_and_comparison_and_supports_factual_draft(
    client, api_key, image_bytes, monkeypatch
):
    container = client.app.state.container
    container.settings.candidate_retention_seconds = 86400
    monkeypatch.setattr(container.settings, "aiand_api_key", "")
    raw = image_bytes()
    headers = _headers(api_key)
    work = client.post(
        "/v1/works",
        headers=headers,
        data={
            "catalog_id": "handoff",
            "title": "Artist's registered original",
            "claimant": "Painter",
        },
        files={"file": ("original.png", raw, "image/png")},
    )
    assert work.status_code == 201, work.text
    data = {
        "catalog_id": "handoff",
        "intended_use": "commercial resale",
        "country_code": "de",
        "source_url": "https://seller.example/listing/art",
        "use_context": json.dumps({"platform": "Artist marketplace", "channel": "web"}),
    }
    response = client.post(
        "/v1/scans",
        headers={**headers, "Idempotency-Key": "flag-context-001"},
        data=data,
        files={"file": ("copy.png", raw, "image/png")},
    )
    assert response.status_code == 202, response.text
    scan = response.json()
    assert scan["admin_review"]["status"] == "needs_review"
    assert scan["submission_context"]["source_url"] == data["source_url"]
    assert scan["submission_context"]["country_code"] == "DE"
    assert scan["evidence_packet"]["submission_context"] == scan["submission_context"]
    [record] = client.get("/v1/admin/user-detections", headers=headers).json()
    assert record["scan_id"] == scan["id"]
    assert record["source_url"] == data["source_url"]
    assert record["source_metadata"]["basis"] == "submitter_url_declaration"
    assert record["country_basis"] == "submitter_declaration_not_verified_residence"
    assert record["jurisdiction"] == "EU"
    assert record["matched_work"]["id"] == work.json()["id"]
    assert record["matched_work"]["claimant"] == "Painter"
    assert record["candidate_media_status"] == "available"
    assert client.get(record["candidate_media_url"], headers=headers).content == raw
    assert client.get(record["reference_media_url"], headers=headers).content == raw
    assert record["review_case"]["id"]
    assert record["takedown_eligible"] is True
    notice = client.post(
        "/v1/admin/takedowns/drafts",
        headers=headers,
        json={**_notice_payload(scan["id"]), "jurisdiction": "DE"},
    )
    assert notice.status_code == 201, notice.text
    assert notice.json()["jurisdiction"] == "EU"
    assert data["source_url"] in notice.json()["body"]
    assert "Artist's registered original" in notice.json()["body"]
    assert notice.json()["recipient_country_code"] is None

    async def unexpected_generation(*_args, **_kwargs):
        pytest.fail("Reading a saved notice must not regenerate it")

    monkeypatch.setattr(AiAndClient, "draft_notice_result", unexpected_generation)
    saved = client.get(f"/v1/admin/takedowns/drafts?scan_id={scan['id']}", headers=headers)
    assert saved.status_code == 200
    assert saved.json()[0]["id"] == notice.json()["id"]
    assert saved.json()[0]["body"] == notice.json()["body"]
    unrelated = client.get("/v1/admin/takedowns/drafts?scan_id=scn_other", headers=headers)
    assert unrelated.json() == []
    other_key = generate_api_key(container.settings.api_key_pepper)
    with container.database.system_session() as db:
        db.add(Tenant(id="tn_other_notices", slug="other-notices", name="Other reviewer"))
        db.commit()
        db.add(
            ApiCredential(
                tenant_id="tn_other_notices",
                name="Other reviewer",
                prefix=other_key.prefix,
                secret_digest=other_key.digest,
                role="REVIEWER",
                scopes=["review:read"],
            )
        )
        db.commit()
    for endpoint in [
        "/v1/admin/takedowns/drafts",
        f"/v1/admin/takedowns/drafts?scan_id={scan['id']}",
    ]:
        assert client.get(endpoint, headers=_headers(other_key.secret)).json() == []
    different_url = client.post(
        "/v1/scans",
        headers={**headers, "Idempotency-Key": "flag-context-001"},
        data={**data, "source_url": "https://seller.example/different"},
        files={"file": ("copy.png", raw, "image/png")},
    )
    assert different_url.status_code == 409
    decided = client.post(
        f"/v1/review-cases/{record['review_case']['id']}/actions",
        headers=headers,
        json={
            "event_type": "DECIDED",
            "state": "RESOLVED",
            "disposition": "NEEDS_LICENSE",
            "note": "Human reviewed the registered work and submitted image.",
        },
    )
    assert decided.status_code == 201, decided.text
    refreshed = client.get(
        f"/v1/admin/user-detections?scan_id={scan['id']}", headers=headers
    ).json()[0]
    assert refreshed["review_case"]["state"] == "RESOLVED"
    assert refreshed["review_case"]["disposition"] == "NEEDS_LICENSE"
    reopened = client.post(
        f"/v1/review-cases/{record['review_case']['id']}/actions",
        headers=headers,
        json={
            "event_type": "REOPENED",
            "state": "IN_REVIEW",
            "note": "Verified permission supplied.",
        },
    )
    assert reopened.status_code == 201, reopened.text
    approved = client.post(
        f"/v1/review-cases/{record['review_case']['id']}/actions",
        headers=headers,
        json={
            "event_type": "DECIDED",
            "disposition": "APPROVED_FOR_PUBLICATION",
            "note": "Permission was verified by the operator.",
        },
    )
    assert approved.status_code == 201, approved.text
    approved_record = client.get(
        f"/v1/admin/user-detections?scan_id={scan['id']}", headers=headers
    ).json()[0]
    assert approved_record["takedown_eligible"] is False
    assert "operator approved" in approved_record["takedown_block_reason"]
    refused = client.post(
        "/v1/admin/takedowns/drafts", headers=headers, json=_notice_payload(scan["id"])
    )
    assert refused.status_code == 409


def test_zero_retention_exposes_expired_media_without_losing_review_context(
    client, api_key, image_bytes
):
    headers = _headers(api_key)
    response = client.post(
        "/v1/scans",
        headers={**headers, "Idempotency-Key": "flag-no-media-001"},
        data={"catalog_id": "empty", "intended_use": "editorial"},
        files={"file": ("image.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 202, response.text
    [record] = client.get("/v1/admin/user-detections", headers=headers).json()
    assert record["category"] == "ASSESSMENT_GAP"
    assert record["candidate_media_status"] == "expired"
    assert record["candidate_media_url"] is None
    assert record["evidence_packet"]
    assert record["takedown_eligible"] is False


def test_authorized_catalog_match_is_visible_but_cannot_generate_a_copyright_notice(
    client, api_key, image_bytes
):
    headers = _headers(api_key)
    raw = image_bytes()
    registered = client.post(
        "/v1/works",
        headers=headers,
        data={
            "catalog_id": "permitted",
            "title": "Permitted original",
            "claimant": "Fixture owner",
            "claim_state": "CORROBORATED",
            "rights_path": "EXISTING_LICENSE",
            "allowed_uses": json.dumps(["editorial"]),
        },
        files={"file": ("original.png", raw, "image/png")},
    )
    assert registered.status_code == 201, registered.text
    scan = client.post(
        "/v1/scans",
        headers={**headers, "Idempotency-Key": "flag-permitted-001"},
        data={"catalog_id": "permitted", "intended_use": "editorial"},
        files={"file": ("copy.png", raw, "image/png")},
    )
    assert scan.status_code == 202, scan.text
    assert scan.json()["policy_action"] == "PASS_BY_POLICY"
    [record] = client.get("/v1/admin/user-detections", headers=headers).json()
    assert record["matched_work_id"] == registered.json()["id"]
    assert record["takedown_eligible"] is False
    assert "authoriz" in record["takedown_block_reason"]
    notice = client.post(
        "/v1/admin/takedowns/drafts", headers=headers, json=_notice_payload(scan.json()["id"])
    )
    assert notice.status_code == 409
    assert notice.json()["detail"]["code"] == "COPYRIGHT_NOTICE_NOT_SUPPORTED"


@pytest.mark.parametrize(
    "source_url",
    ["file:///tmp/image", "javascript:alert(1)", "https://secret:password@host.example/image"],
)
def test_upload_source_url_validation(client, api_key, image_bytes, source_url):
    response = client.post(
        "/v1/scans",
        headers={**_headers(api_key), "Idempotency-Key": "flag-invalid-url-001"},
        data={"catalog_id": "default", "intended_use": "editorial", "source_url": source_url},
        files={"file": ("image.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 422
    with client.app.state.container.database.session_factory() as db:
        assert list(db.scalars(select(Scan))) == []
