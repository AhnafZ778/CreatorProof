import json

import pytest


def auth(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def register(client, api_key, raw, *, title="Reference", claim_state="CORROBORATED"):
    return client.post(
        "/v1/works",
        headers=auth(api_key),
        data={
            "title": title,
            "catalog_id": "demo-catalog",
            "rights_path": "EXISTING_LICENSE",
            "allowed_uses": json.dumps(["marketing/social"]),
            "claimant": "Demo Rightsholder",
            "claim_state": claim_state,
        },
        files={"file": ("reference.png", raw, "image/png")},
    )


def scan(
    client,
    api_key,
    raw,
    *,
    key="idem-00000001",
    catalog_id="demo-catalog",
    intended_use="marketing/social",
):
    return client.post(
        "/v1/scans",
        headers={**auth(api_key), "Idempotency-Key": key},
        data={"catalog_id": catalog_id, "intended_use": intended_use},
        files={"file": ("candidate.png", raw, "image/png")},
    )


def test_exact_match_keeps_evidence_separate_from_policy(client, api_key, image_bytes):
    raw = image_bytes(0)
    registered = register(client, api_key, raw)
    assert registered.status_code == 201, registered.text

    response = scan(client, api_key, raw)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["state"] == "COMPLETED"
    assert body["match_status"] == "MATCH_FOUND"
    assert body["policy_action"] == "PASS_BY_POLICY"
    assert body["rights_path"] == "EXISTING_LICENSE"
    assert body["top_match_work_id"] == registered.json()["id"]
    top_match = body["evidence_packet"]["matches"][0]
    assert top_match["exact_sha256"] is True
    visual = top_match["visualization"]
    assert visual["schema"] == "creatorproof.visual_evidence.v1"
    assert visual["coordinate_space"] == "NORMALIZED_IMAGE_0_1"
    assert visual["query_size"] == [320, 240]
    assert visual["reference_size"] == [320, 240]
    assert visual["regions"][0]["kind"] == "EXACT_BINARY_MATCH"
    assert visual["homography_query_to_reference"] is not None
    assert body["evidence_packet"]["proof"]["packet_hash_sha256"]
    decision = body["evidence_packet"]["decision"]
    assert decision["policy_version"] == decision["policy_version_id"]
    assert decision["policy_version_id"].startswith("pol_")
    assert decision["policy_digest_sha256"]
    assert decision["policy_inputs"]["matched_work"]["claim_state"] == "CORROBORATED"
    assert decision["policy_inputs"]["matched_work"]["source"] == "PERSISTED_CLAIM_AND_LICENSE_ROWS"
    assert decision["policy_inputs"]["intended_use"] == "marketing/social"
    assert decision["policy_trace"]["schema"] == "creatorproof.policy_trace.v1"
    assert len(decision["policy_trace"]["trace_digest_sha256"]) == 64
    telemetry = body["evidence_packet"]["runtime_telemetry"]
    assert telemetry["schema"] == "creatorproof.runtime_telemetry.v1"
    assert telemetry["timings_ms"]["evidence_pipeline_precommit"]["count"] == 1
    assert telemetry["score_summaries"]["copy_evidence_index"]["maximum"] == 1.0
    assert telemetry["semantics"].endswith("NOT_ACCURACY_METRICS")
    assert "copyright clear" not in json.dumps(body).lower()


def test_hard_negative_is_only_no_match_in_checked_sources(client, api_key, image_bytes):
    assert register(client, api_key, image_bytes(0)).status_code == 201
    result = scan(client, api_key, image_bytes(35), key="idem-hard-negative")
    assert result.status_code == 202, result.text
    body = result.json()
    assert body["match_status"] in {"NO_MATCH_IN_CHECKED_SOURCES", "INCONCLUSIVE"}
    if body["match_status"] == "NO_MATCH_IN_CHECKED_SOURCES":
        assert body["policy_action"] == "PASS_BY_POLICY"
        assert "AI_ORIGIN_INFORMATIONAL_ONLY" in body["reason_codes"]
    assert body["evidence_packet"]["scope"]["coverage_status"] == "COMPLETE"
    assert body["evidence_packet"]["scope"]["complete_for_declared_catalog"] is True
    assert body["evidence_packet"]["scope"]["snapshot_digest_sha256"]
    assert body["evidence_packet"]["scope"]["catalog_version"].startswith("manifest_")
    assert body["evidence_packet"]["scope"]["query_counts"] == {
        "whole_image": 1,
        "regional": 0,
    }
    assert any(
        "not a legal infringement" in item for item in body["evidence_packet"]["limitations"]
    )


def test_idempotency_replays_same_scan(client, api_key, image_bytes):
    raw = image_bytes(0)
    first = scan(client, api_key, raw, key="idem-repeat-001")
    second = scan(client, api_key, raw, key="idem-repeat-001")
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["request_digest"] == second.json()["request_digest"]


def test_idempotency_rejects_same_key_for_different_candidate(client, api_key, image_bytes):
    first = scan(client, api_key, image_bytes(0), key="idem-payload-bound")
    second = scan(client, api_key, image_bytes(27), key="idem-payload-bound")

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"
    assert second.json()["detail"]["existing_scan_id"] == first.json()["id"]


@pytest.mark.parametrize(
    "changed_request",
    [
        {"catalog_id": "other-catalog"},
        {"intended_use": "editorial/review"},
    ],
)
def test_idempotency_rejects_changed_request_scope(client, api_key, image_bytes, changed_request):
    raw = image_bytes(2)
    key = f"idem-changed-{next(iter(changed_request))}"
    first = scan(client, api_key, raw, key=key)
    second = scan(client, api_key, raw, key=key, **changed_request)

    assert first.status_code == 202
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "IDEMPOTENCY_PAYLOAD_MISMATCH"


def test_empty_catalog_is_scope_incomplete_and_never_passes(client, api_key, image_bytes):
    result = scan(client, api_key, image_bytes(3), key="idem-empty-catalog")

    assert result.status_code == 202, result.text
    body = result.json()
    assert body["match_status"] == "SCOPE_INCOMPLETE"
    assert body["policy_action"] == "REVIEW"
    assert "DECLARED_CATALOG_EMPTY" in body["reason_codes"]
    scope = body["evidence_packet"]["scope"]
    assert scope["coverage_status"] == "EMPTY_SCOPE"
    assert scope["complete_for_declared_catalog"] is False
    assert scope["eligible_reference_count"] == 0


def test_asserted_claim_cannot_authorize_an_exact_match(client, api_key, image_bytes):
    raw = image_bytes(4)
    assert register(client, api_key, raw, claim_state="ASSERTED").status_code == 201

    result = scan(client, api_key, raw, key="idem-asserted-claim")

    assert result.status_code == 202, result.text
    body = result.json()
    assert body["match_status"] == "MATCH_FOUND"
    assert body["policy_action"] == "REVIEW"
    assert "MATCHED_CLAIM_NOT_CORROBORATED" in body["reason_codes"]


def test_legacy_work_fields_cannot_authorize_without_persisted_rights_rows(
    client, api_key, image_bytes
):
    raw = image_bytes(41)
    registered = register(client, api_key, raw)
    assert registered.status_code == 201

    from sqlalchemy import delete

    from app.models import Claim, License, Work

    container = client.app.state.container
    db = container.database.session_factory()
    try:
        work_id = registered.json()["id"]
        # Leave the compatibility projection looking fully authorized while
        # removing the authoritative facts a scan is permitted to trust.
        work = db.get(Work, work_id)
        assert work.claim_state == "CORROBORATED"
        assert work.rights_path == "EXISTING_LICENSE"
        assert work.allowed_uses == ["marketing/social"]
        db.execute(delete(License).where(License.work_id == work_id))
        db.execute(delete(Claim).where(Claim.work_id == work_id))
        db.commit()
    finally:
        db.close()

    result = scan(client, api_key, raw, key="idem-persisted-rights-required")
    assert result.status_code == 202, result.text
    decision = result.json()["evidence_packet"]["decision"]
    assert decision["policy_action"] == "REVIEW"
    assert decision["authorizing_license_id"] is None
    assert "NO_RECORDED_CLAIM" in decision["policy_evaluation"]["missing_facts"]
    assert "NO_RECORDED_LICENSE" in decision["policy_evaluation"]["missing_facts"]


def test_revoked_claim_cannot_authorize_an_exact_match(client, api_key, image_bytes):
    raw = image_bytes(5)
    assert register(client, api_key, raw, claim_state="REVOKED").status_code == 201

    result = scan(client, api_key, raw, key="idem-revoked-claim")

    assert result.status_code == 202, result.text
    body = result.json()
    assert body["match_status"] == "MATCH_FOUND"
    assert body["policy_action"] == "REVIEW"
    assert "MATCHED_CLAIM_REVOKED" in body["reason_codes"]


def test_required_unavailable_origin_lane_routes_an_otherwise_allowed_match_to_review(
    client, api_key, image_bytes
):
    client.app.state.container.settings.synthetic_policy_mode = "REQUIRED"
    raw = image_bytes(6)
    assert register(client, api_key, raw).status_code == 201

    result = scan(client, api_key, raw, key="idem-required-origin")

    assert result.status_code == 202, result.text
    body = result.json()
    assert body["match_status"] == "MATCH_FOUND"
    assert body["policy_action"] == "REVIEW"
    assert "AI_ORIGIN_RESULT_REQUIRES_PRODUCT_REVIEW" in body["reason_codes"]
    origin = body["evidence_packet"]["synthetic_origin"]
    assert origin["policy_mode"] == "REQUIRED"
    assert origin["execution_state"] == "EXECUTED"


def test_disabled_origin_lane_is_skipped_and_cannot_change_policy(client, api_key, image_bytes):
    client.app.state.container.settings.synthetic_policy_mode = "DISABLED"
    raw = image_bytes(7)
    assert register(client, api_key, raw).status_code == 201

    result = scan(client, api_key, raw, key="idem-disabled-origin")

    assert result.status_code == 202, result.text
    body = result.json()
    assert body["match_status"] == "MATCH_FOUND"
    assert body["policy_action"] == "PASS_BY_POLICY"
    assert "AI_ORIGIN_CHECK_DISABLED_BY_POLICY" in body["reason_codes"]
    origin = body["evidence_packet"]["synthetic_origin"]
    assert origin["classification"] == "AI_ORIGIN_CHECK_DISABLED"
    assert origin["policy_mode"] == "DISABLED"
    assert origin["execution_state"] == "SKIPPED_BY_POLICY"


def test_api_key_is_required(client, image_bytes):
    response = client.get("/v1/works")
    # A missing credential is an authentication failure, not a malformed request.
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "MISSING_API_KEY"


def test_style_lane_builds_creator_profile_and_cross_content_map(client, api_key, image_bytes):
    first = register(client, api_key, image_bytes(0), title="Creator sample A")
    second = register(client, api_key, image_bytes(12), title="Creator sample B")
    assert first.status_code == 201
    assert second.status_code == 201

    result = scan(client, api_key, image_bytes(31), key="idem-style-profile")
    assert result.status_code == 202, result.text
    style = result.json()["evidence_packet"]["style_analysis"]

    assert style["schema"] == "creatorproof.style_evidence.v2"
    assert style["provider"] == "diagnostic-style-signature-v1"
    assert style["learned_provider_active"] is False
    assert style["calibration_state"] == "DIAGNOSTIC_ONLY_NOT_ATTRIBUTION"
    assert style["readout"]["method"] == "RAW_POOL_COSINE"
    assert style["top_profiles"][0]["creator"] == "Demo Rightsholder"
    assert style["top_profiles"][0]["sample_count"] == 2
    assert style["top_profiles"][0]["profile_strength"] == "LIMITED_PROFILE"
    assert style["top_profiles"][0]["profile_source"] == "PROTOTYPE_CLAIMANT_GROUPING"
    assert style["top_profiles"][0]["profile_authorized"] is False
    assert style["top_profiles"][0]["raw_pool_similarity"] is not None
    assert style["decision"]["evidence_tier"] == "DIAGNOSTIC"
    assert style["decision"]["review_recommended"] is False
    tile_map = style["diagnostics"]["tile_map"]
    assert tile_map["semantics"] == "CROSS_CONTENT_STYLE_DIAGNOSTIC_NOT_PIXEL_CORRESPONDENCE"
    assert len(tile_map["query_cells"]) == 16
    assert len(tile_map["reference_cells"]) == 16


def test_demo_sized_catalog_is_verified_exhaustively_beyond_top_k(
    client,
    api_key,
    image_bytes,
):
    for seed in range(9):
        response = register(
            client,
            api_key,
            image_bytes(seed),
            title=f"Catalog work {seed}",
        )
        assert response.status_code == 201, response.text

    result = scan(client, api_key, image_bytes(40), key="idem-exhaustive-demo-catalog")
    assert result.status_code == 202, result.text
    scope = result.json()["evidence_packet"]["scope"]

    assert scope["eligible_reference_count"] == 9
    assert scope["candidate_limit"] == 9
    assert scope["nominated_candidate_count"] == 9
    assert scope["verified_candidate_count"] == 9
    assert scope["omitted_candidate_count"] == 0
    assert scope["coverage_status"] == "COMPLETE"
