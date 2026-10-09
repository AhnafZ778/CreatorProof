from copy import deepcopy

import pytest
from sqlalchemy import select

from app.models import ReviewCase, Scan, Tenant
from app.services.evidence import canonical_hash
from app.services.evidence_assessment import assess_evidence_packet
from app.services.evidence_matrix import normalized_signals


def _assessment(score=0.973765):
    packet = {
        "decision": {"match_status": "MATCH_FOUND", "policy_action": "REVIEW"},
        "matches": [
            {"work_id": "wrk_a", "fusion": {"match_supported": True, "evidence_index": score}}
        ],
        "synthetic_origin": {"classification": "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"},
        "provenance": {"status": "NOT_CHECKED"},
        "scope": {
            "coverage_status": "COMPLETE",
            "eligible_reference_count": 2,
            "capabilities": {"exact_sha256": {"references_checked": 2}},
        },
    }
    packet["proof"] = {"packet_hash_sha256": canonical_hash(packet)}
    return packet


def test_ratings_keep_score_semantics_and_never_assign_missing_origin_a_zero():
    packet = _assessment()
    original = deepcopy(packet)
    ratings = assess_evidence_packet(packet, normalized_signals(packet))["lanes"]
    assert ratings["COPY"]["rating"]["display"] == "97.4"
    assert ratings["COPY"]["rating"]["conclusive"] is True
    assert ratings["COPY"]["rating"]["basis"] == "COPY_FUSION_INDEX_NOT_PROBABILITY"
    assert ratings["ORIGIN"]["rating"]["value"] is None
    assert ratings["ORIGIN"]["rating"]["display"] == "—"
    assert ratings["INTEGRITY"]["rating"]["grade"] == "Hash verified"
    assert ratings["SOURCE_COVERAGE"]["rating"]["display"] == "2 / 2"
    assert packet == original


@pytest.mark.parametrize("score", [None, True, -0.5, 2.0])
def test_invalid_or_missing_scores_do_not_become_confidence_ratings(score):
    packet = _assessment(score)
    rating = assess_evidence_packet(packet, normalized_signals(packet))["lanes"]["COPY"]["rating"]
    assert rating["value"] is None
    assert rating["display"] == "—"


def test_packet_hash_is_recomputed_before_showing_verified():
    packet = _assessment()
    packet["decision"]["policy_action"] = "PASS_BY_POLICY"
    rating = assess_evidence_packet(packet, normalized_signals(packet))["lanes"]["INTEGRITY"][
        "rating"
    ]
    assert rating["display"] == "Mismatch"
    assert rating["conclusive"] is False


def test_failed_assessments_cannot_display_partial_scores_as_completed_measurements():
    packet = _assessment()
    result = assess_evidence_packet(packet, normalized_signals(packet), failed=True)
    assert all(row["rating"]["value"] is None for row in result["lanes"].values())
    assert all(row["rating"]["display"] == "—" for row in result["lanes"].values())


def _linked_scans(client, api_key, image_bytes):
    client.app.state.container.settings.candidate_retention_seconds = 3600
    headers = {"X-API-Key": api_key}
    raw = image_bytes()
    response = client.post(
        "/v1/works",
        headers=headers,
        data={"catalog_id": "rated", "title": "Rated artwork"},
        files={"file": ("art.png", raw, "image/png")},
    )
    assert response.status_code == 201, response.text
    scan_ids = []
    for key in ["original", "refreshed"]:
        response = client.post(
            "/v1/scans",
            headers={**headers, "Idempotency-Key": key},
            data={"catalog_id": "rated", "intended_use": "editorial"},
            files={"file": ("art.png", raw, "image/png")},
        )
        assert response.status_code == 202, response.text
        assert response.json()["state"] == "COMPLETED"
        scan_ids.append(response.json()["id"])
    original, source = scan_ids
    assert client.post(f"/v1/admin/stored-cases/{original}", headers=headers).status_code == 200
    with client.app.state.container.database.session_factory() as db:
        case = db.scalar(select(ReviewCase).where(ReviewCase.scan_id == original))
        case.archive_record = {**case.archive_record, "assessment_scan_id": source}
        db.commit()
    return headers, original, source


def test_refreshed_assessment_is_hash_bound_and_original_matrix_stays_intact(
    client, api_key, image_bytes
):
    headers, original, source = _linked_scans(client, api_key, image_bytes)
    result = client.get(f"/v1/scans/{original}/evidence-matrix", headers=headers).json()
    assert result["scan_id"] == original
    assert result["assessment_source"]["scan_id"] == source
    assert result["assessment_source"]["refreshed"] is True
    assert result["assessment"]["lanes"]["COPY"]["rating"]["display"] == "100.0"
    assert all(row["scan_id"] == original for row in result["signals"])
    assert all(row["scan_id"] == source for row in result["assessment_signals"])
    assert result["packet_hash_sha256"] != result["assessment_source"]["packet_hash_sha256"]


@pytest.mark.parametrize(
    "tamper", ["candidate", "catalog", "packet", "reference", "tenant", "work"]
)
def test_wrong_or_tampered_assessment_links_fall_back_without_exposing_other_records(
    client, api_key, image_bytes, tamper
):
    headers, original, source_id = _linked_scans(client, api_key, image_bytes)
    with client.app.state.container.database.session_factory() as db:
        source = db.get(Scan, source_id)
        case = db.scalar(select(ReviewCase).where(ReviewCase.scan_id == original))
        if tamper == "candidate":
            source.candidate_sha256 = "f" * 64
        elif tamper == "catalog":
            source.catalog_id = "another"
        elif tamper == "packet":
            source.evidence_packet = {**source.evidence_packet, "changed": True}
        elif tamper == "reference":
            case.archive_record = {**case.archive_record, "reference_sha256": "f" * 64}
        elif tamper == "work":
            source.top_match_work_id = "wrk_unrelated"
        else:
            db.add(Tenant(id="tn_other_ratings", slug="other-ratings", name="Other"))
            db.flush()
            other = Scan(
                tenant_id="tn_other_ratings",
                idempotency_key="other",
                catalog_id="rated",
                intended_use="editorial",
                candidate_sha256=source.candidate_sha256,
                candidate_phash=source.candidate_phash,
                state="COMPLETED",
                evidence_packet=source.evidence_packet,
            )
            db.add(other)
            db.flush()
            case.archive_record = {**case.archive_record, "assessment_scan_id": other.id}
        db.commit()
    result = client.get(f"/v1/scans/{original}/evidence-matrix", headers=headers).json()
    assert result["assessment_source"]["refreshed"] is False
    assert result["assessment_source"]["scan_id"] == original
