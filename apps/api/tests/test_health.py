def test_health_and_readiness(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["version"] == "0.10.0"
    assert health.json()["build_signature"] == "MODEL-ACCURACY-HARDENING-2026.08.10"
    assert health.json()["model_bundle_id"] == "creatorproof-runtime-ready-evidence-v1"
    assert health.json()["style_profile_manifest_state"] == "VALID"
    assert health.json()["style_profile_count"] == 0
    assert health.json()["synthetic_calibration_state"] == "NOT_CONFIGURED"
    assert health.json()["copy_exhaustive_verification_max_entries"] == 64
    assert health.json()["model_bundle_declared_state_verified"] is False
    assert health.json()["model_bundle_demo_ready"] is False
    assert health.json()["model_bundle_runtime_artifact_failures"] == ["copy-retrieval-sscd"]
    assert health.json()["model_bundle_application_revision_matches"] is True
    assert health.json()["model_bundle_runtime_environment_matches"] is True
    assert health.json()["model_bundle_manifest_state"] == "VALID"
    assert health.json()["model_bundle_qualification_state"] == "RUNTIME_READY"
    assert len(health.json()["model_bundle_manifest_digest"]) == 64
    assert "visible_marker_available" in health.json()
    assert health.json()["ai_provider"] == "sscd-disc-mixup-torchscript"
    assert isinstance(health.json()["ai_available"], bool)
    assert health.json()["style_provider"] == "diagnostic-style-signature-v1"
    assert health.json()["style_available"] is True
    assert health.json()["style_learned"] is False
    assert isinstance(health.json()["synthetic_available"], bool)
    assert health.json()["synthetic_provider"] == "evidence-family-synthetic-ensemble-v3"
    assert health.json()["synthetic_primary_provider"] is None
    assert health.json()["synthetic_primary_state"] == "DISABLED"
    assert health.json()["synthetic_local_fallback_available"] is False
    assert isinstance(health.json()["synthetic_routing"], dict)
    assert "synthetic_batched_detectors" in health.json()
    assert isinstance(health.json()["synthetic_evidence_families"], list)
    assert health.json()["provenance_provider"]
    assert health.json()["proof_provider"]
    assert health.json()["proof_scope"]
    assert health.json()["origin_policy_mode"] == "INFORMATIONAL"
    assert health.json()["copy_retrieval_requirement"] == "BASELINE_ALLOWED"

    ready = client.get("/readyz")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["job_backend"] == "inline"


def test_openapi_exposes_typed_coverage_contract(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]

    assert "CorpusScopeRead" in schemas
    assert "EvidencePacketRead" in schemas
    assert schemas["CoverageStatus"]["enum"] == [
        "COMPLETE",
        "EMPTY_SCOPE",
        "PARTIAL",
        "DEGRADED",
        "TRUNCATED",
        "FAILED",
    ]
    required_scope_fields = set(schemas["CorpusScopeRead"]["required"])
    assert {
        "snapshot_digest_sha256",
        "catalog_version",
        "coverage_status",
        "coverage_reason_codes",
        "eligible_reference_count",
        "verified_candidate_count",
        "capabilities",
    } <= required_scope_fields
