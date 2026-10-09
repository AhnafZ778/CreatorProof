from __future__ import annotations

import json
from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin
from sqlalchemy import select

from app.models import EvidenceMatrix, EvidenceSignal, ProvenanceRecord
from app.providers.provenance import C2PAToolProvenanceProvider
from app.services.evidence_matrix import LANES, matrix_summary, normalized_signals
from app.services.provenance_records import inspect_metadata, normalized_status


def _packet(match="MATCH_FOUND", coverage="COMPLETE", origin=None, geometry=True):
    return {
        "candidate_commitment": {"sha256": "a" * 64},
        "scope": {"coverage_status": coverage},
        "decision": {"match_status": match, "policy_action": "REVIEW"},
        "proof": {"packet_hash_sha256": "b" * 64},
        "matches": [
            {
                "exact_sha256": False,
                "retrieval_score": 0.99,
                "geometry": {
                    "validated": geometry,
                    "alignment_grade": "STRICT" if geometry else "NONE",
                },
                "visualization": {"regions": [{"untrusted": "region"}]},
                "fusion": {
                    "match_supported": match == "MATCH_FOUND",
                    "review_supported": match == "INCONCLUSIVE",
                    "evidence_index": 0.8,
                },
            }
        ],
        "provenance": {"status": "NOT_PRESENT", "provider": "fixture"},
        "synthetic_origin": origin or {"classification": "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"},
    }


@pytest.mark.parametrize(
    "raw,available,reasons,expected",
    [
        ("VALID_TRUSTED", True, [], "VALID"),
        ("VALID_UNTRUSTED", True, [], "VALID_BUT_UNTRUSTED"),
        ("INVALID", True, [], "INVALID"),
        ("NOT_PRESENT", True, [], "ABSENT"),
        ("NOT_CHECKED", False, [], "PROVIDER_UNAVAILABLE"),
        ("NOT_CHECKED", True, ["C2PA_FORMAT_UNSUPPORTED"], "UNSUPPORTED"),
        ("ERROR", True, ["C2PA_OUTPUT_NOT_JSON"], "PARSE_ERROR"),
        ("ERROR", True, ["C2PA_INSPECTION_TIMEOUT"], "PROVIDER_UNAVAILABLE"),
    ],
)
def test_explicit_provenance_states(raw, available, reasons, expected):
    assert normalized_status(raw, reasons, available=available) == expected


def test_invalid_geometry_does_not_create_region_or_copy_explanation():
    signals = normalized_signals(_packet(match="INCONCLUSIVE", geometry=False))
    assert {row["lane"] for row in signals} == set(LANES)
    assert all(not row["artifact_refs"] for row in signals if row["lane"] == "COPY")
    assert (
        next(row for row in signals if row["signal_type"] == "GEOMETRY")["status"] == "INCONCLUSIVE"
    )
    assert (
        next(row for row in signals if row["signal_type"] == "RETRIEVAL")["status"]
        == "INCONCLUSIVE"
    )


@pytest.mark.parametrize(
    "match,coverage,origin,expected,abstain",
    [
        ("MATCH_FOUND", "COMPLETE", None, "PARTIALLY_SUPPORTED", False),
        ("INCONCLUSIVE", "COMPLETE", None, "INCONCLUSIVE", True),
        ("NO_MATCH_IN_CHECKED_SOURCES", "PARTIAL", None, "INSUFFICIENT_COVERAGE", True),
        (
            "MATCH_FOUND",
            "COMPLETE",
            {"classification": "INCONCLUSIVE_DETECTOR_DISAGREEMENT"},
            "CONTRADICTORY",
            True,
        ),
    ],
)
def test_matrix_abstention_is_separate_from_policy(match, coverage, origin, expected, abstain):
    packet = _packet(match=match, coverage=coverage, origin=origin)
    result = matrix_summary(packet, normalized_signals(packet))
    assert result["final_status"] == expected
    assert result["abstention"] is abstain
    assert packet["decision"]["policy_action"] == "REVIEW"


def test_ai_origin_signal_cannot_become_copy_match():
    packet = _packet(
        match="NO_MATCH_IN_CHECKED_SOURCES",
        geometry=False,
        origin={
            "classification": "LIKELY_AI_GENERATED",
            "members": [{"provider": "fixture", "score": 0.9}],
            "fused_detector_score": 0.9,
        },
    )
    signals = normalized_signals(packet)
    assert (
        next(row for row in signals if row["signal_type"] == "ORIGIN_ASSESSMENT")["status"]
        == "SUPPORTED"
    )
    assert all(
        row["status"] != "SUPPORTED" for row in signals if row["signal_type"] == "COPY_FUSION"
    )
    assert all(not row["artifact_refs"] for row in signals)


def test_provider_failure_has_all_lanes_and_abstention():
    packet = {"decision": {"match_status": "ERROR"}}
    signals = normalized_signals(packet, failed=True)
    assert len(signals) == len(LANES)
    assert matrix_summary(packet, signals, failed=True)["final_status"] == "PROVIDER_FAILURE"


def test_metadata_inspection_redacts_pii_and_does_not_assume_stripping(image_bytes):
    raw = image_bytes()
    summary = inspect_metadata(raw)
    assert summary["removal_status"] == "UNKNOWN"
    assert "METADATA_ABSENT_NOT_PROOF_OF_REMOVAL" in summary["reason_codes"]
    image = Image.open(BytesIO(raw))
    exif = Image.Exif()
    exif[305] = "Editor version 1"
    exif[315] = "private creator@example.com"
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)
    summary = inspect_metadata(output.getvalue())
    assert summary["exif"]["software"] == "Editor version 1"
    assert "creator@example.com" not in json.dumps(summary)


def test_xmp_injection_is_never_executed_or_added_to_evidence(image_bytes):
    image = Image.open(BytesIO(image_bytes()))
    info = PngImagePlugin.PngInfo()
    info.add_text(
        "XML:com.adobe.xmp", '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x>&x;</x>'
    )
    output = BytesIO()
    image.save(output, format="PNG", pnginfo=info)
    summary = inspect_metadata(output.getvalue())
    assert "XMP_UNSAFE_OR_OVERSIZED" in summary["reason_codes"]
    assert not summary["xmp"]["fields"]


def test_c2pa_actions_ingredients_and_ai_edit_are_retained_without_personal_data():
    payload = {
        "active_manifest": "private-repository-id",
        "manifests": {
            "private-repository-id": {
                "claim_generator": "Fixture generator",
                "assertions": [
                    {
                        "label": "c2pa.actions",
                        "data": {
                            "actions": [
                                {
                                    "action": "c2pa.created",
                                    "digitalSourceType": "trainedAlgorithmicMedia",
                                },
                                {
                                    "action": "c2pa.edited",
                                    "parameters": {"modelName": "Fixture-model"},
                                },
                            ]
                        },
                    }
                ],
                "ingredients": [
                    {"instance_id": "private-parent@example.com", "relationship": "parentOf"},
                    {"instance_id": "private-ingredient", "relationship": "componentOf"},
                ],
            }
        },
    }
    summary = C2PAToolProvenanceProvider._summary(payload)
    assert len(summary["ingredients"]) == 2
    assert summary["ai_assertion_present"]
    assert summary["model_names"] == ["Fixture-model"]
    assert len(summary["creation_actions"]) == len(summary["editing_actions"]) == 1
    assert "private-parent@example.com" not in json.dumps(summary)


def _register(client, headers, raw):
    response = client.post(
        "/v1/works",
        headers=headers,
        data={"title": "Owned fixture", "catalog_id": "phase1"},
        files={"file": ("fixture.png", raw, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_scan_persists_matrix_and_provenance_before_zero_retention(client, api_key, image_bytes):
    headers = {"X-API-Key": api_key}
    _register(client, headers, image_bytes())
    response = client.post(
        "/v1/scans",
        headers={**headers, "Idempotency-Key": "phase1-evidence-1"},
        data={"catalog_id": "phase1", "intended_use": "editorial"},
        files={"file": ("fixture.png", image_bytes(), "image/png")},
    )
    assert response.status_code == 202, response.text
    scan = response.json()
    assert scan["state"] == "COMPLETED", scan
    result = client.get(f"/v1/scans/{scan['id']}/evidence-matrix", headers=headers)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["persisted"] and body["legal_conclusion"] is None
    assert body["packet_hash_sha256"] == scan["evidence_packet"]["proof"]["packet_hash_sha256"]
    assert {row["lane"] for row in body["signals"]} == set(LANES)
    assert all(row["started_at"] and row["completed_at"] for row in body["signals"])
    provenance = client.get(f"/v1/scans/{scan['id']}/provenance", headers=headers)
    assert provenance.status_code == 200, provenance.text
    assert provenance.json()["status"] == "PROVIDER_UNAVAILABLE"
    assert (
        client.post(f"/v1/scans/{scan['id']}/provenance/inspect", headers=headers).status_code
        == 404
    )
    correction = client.post(
        f"/v1/scans/{scan['id']}/evidence-matrix/corrections",
        headers=headers,
        json={"reason": "Reproject recorded facts with corrected normalizer"},
    )
    assert correction.status_code == 201, correction.text
    assert correction.json()["version"] == 2
    newer = client.get(f"/v1/scans/{scan['id']}/evidence-matrix", headers=headers).json()
    assert newer["version"] == 2
    assert len(newer["signals"]) == len(body["signals"])
    assert client.get(f"/v1/scans/{scan['id']}/evidence-matrix").status_code == 401
    with client.app.state.container.database.session_factory() as db:
        assert len(db.scalars(select(EvidenceMatrix)).all()) == 2
        assert len(db.scalars(select(EvidenceSignal)).all()) == 2 * len(body["signals"])
        assert (
            len(
                db.scalars(
                    select(ProvenanceRecord).where(
                        ProvenanceRecord.subject_type == "scan",
                    )
                ).all()
            )
            == 1
        )
        assert (
            len(
                db.scalars(
                    select(ProvenanceRecord).where(
                        ProvenanceRecord.subject_type == "work",
                    )
                ).all()
            )
            == 1
        )


def test_work_provenance_survives_as_immutable_history_after_media_deletion(
    client,
    api_key,
    image_bytes,
):
    headers = {"X-API-Key": api_key}
    work_id = _register(client, headers, image_bytes())
    result = client.post(f"/v1/works/{work_id}/provenance/inspect", headers=headers)
    assert result.status_code == 201, result.text
    token = client.post(f"/v1/works/{work_id}/verification-token", headers=headers, json={}).json()[
        "token"
    ]
    result = client.delete(f"/v1/works/{work_id}", headers=headers)
    assert result.status_code == 200, result.text
    assert client.get(f"/v1/works/{work_id}/provenance", headers=headers).status_code == 404
    assert client.get(f"/verify/{token}").status_code in {404, 410}
    assert client.get("/v1/works", headers=headers).json() == []


def test_reinspection_rejects_changed_reference_bytes(client, api_key, image_bytes):
    from app.models import Work

    headers = {"X-API-Key": api_key}
    work_id = _register(client, headers, image_bytes())
    container = client.app.state.container
    with container.database.session_factory() as db:
        work = db.get(Work, work_id)
        key = work.storage_key
        count = len(db.scalars(select(ProvenanceRecord)).all())
    container.storage.put(key, image_bytes(17))
    response = client.post(f"/v1/works/{work_id}/provenance/inspect", headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "SOURCE_IMAGE_INTEGRITY_MISMATCH"
    with container.database.session_factory() as db:
        assert len(db.scalars(select(ProvenanceRecord)).all()) == count
