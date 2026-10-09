import importlib.metadata
import json
import platform

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.model_bundle import file_sha256, source_tree_revision


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
    # The service's optional model package versions are deployment-specific;
    # liveness/readiness must expose that result without assuming pinned wheels
    # are installed in the API test environment. Controlled cases below verify
    # that a match and a drift are reported distinctly and gate qualification.
    assert isinstance(health.json()["model_bundle_runtime_environment_matches"], bool)
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


@pytest.mark.parametrize("package_state", ["MATCH", "VERSION_DRIFT", "MISSING"])
def test_health_and_readiness_truthfully_report_runtime_package_qualification(
    tmp_path, monkeypatch, package_state
):
    # A test-only baseline component has no model artifact prerequisite. This
    # isolates environment qualification from an unrelated missing checkpoint,
    # which would otherwise keep qualification false and conceal a regression.
    lock = tmp_path / "runtime.lock"
    lock.write_text("health runtime contract fixture\n")
    requirement = tmp_path / "requirements-health.txt"
    pinned_version = importlib.metadata.version("pytest")
    requirement.write_text(f"pytest=={pinned_version}\n")
    bundle = {
        "schema": "creatorproof.model_bundle.v1",
        "bundle_id": "health-runtime-contract-fixture",
        "qualification_state": "RUNTIME_READY",
        "application_revision": source_tree_revision(tmp_path),
        "runtime_lock_digest": file_sha256(lock),
        "runtime_environment": {
            "python_major_minor": ".".join(platform.python_version_tuple()[:2]),
            "observed_python": platform.python_version(),
            "packages": {"pytest": pinned_version},
            "requirement_file_digests": {requirement.name: file_sha256(requirement)},
        },
        "domain_id": "HEALTH_CONTRACT_TEST_ONLY",
        "components": [
            {
                "component_id": "health-baseline",
                "role": "BASELINE_DIAGNOSTIC",
                "provider_id": "test-baseline",
                "model_version": "test-v1",
                "preprocessing_id": "test-identity",
                "qualification_state": "RUNTIME_READY",
                "terms_state": "NOT_APPLICABLE",
                "source_revision": "test-fixture-v1",
                "artifact_required": False,
                "artifact_sha256": None,
                "required_for_demo": True,
                "limitations": ["Test-only baseline; not AI model qualification."],
            }
        ],
        "limitations": ["Isolated health contract fixture."],
    }
    manifest = tmp_path / "health-bundle.json"
    manifest.write_text(json.dumps(bundle))
    original_version = importlib.metadata.version

    def observed_version(package):
        if package == "pytest":
            if package_state == "MISSING":
                raise importlib.metadata.PackageNotFoundError(package)
            if package_state == "VERSION_DRIFT":
                return "0.0.0-health-test-drift"
        return original_version(package)

    monkeypatch.setattr("app.services.model_bundle.importlib.metadata.version", observed_version)
    # Relative requirement/source identities resolve as a deployment would,
    # while the production manifest/pins and repository files stay untouched.
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'health.db'}",
        storage_root=tmp_path / "objects",
        job_backend="inline",
        model_bundle_path=manifest,
        runtime_lock_path=lock,
        sscd_model_path=tmp_path / "missing-optional-model.pt",
        style_provider="diagnostic",
        synthetic_detector="off",
        c2pa_mode="off",
        visible_ai_marker_mode="off",
        proof_anchor_mode="none",
        proof_log_path=tmp_path / "proof-log.jsonl",
    )
    with TestClient(create_app(settings)) as client:
        for endpoint, status in (("/healthz", "ok"), ("/readyz", "ready")):
            response = client.get(endpoint)
            assert response.status_code == 200
            body = response.json()
            assert body["status"] == status
            assert body["model_bundle_id"] == "health-runtime-contract-fixture"
            assert body["model_bundle_manifest_state"] == "VALID"
            assert body["model_bundle_qualification_state"] == "RUNTIME_READY"
            assert body["model_bundle_application_revision_matches"] is True
            assert body["model_bundle_runtime_artifact_failures"] == []
            assert body["model_bundle_runtime_environment_matches"] is (package_state == "MATCH")
            assert body["model_bundle_declared_state_verified"] is (package_state == "MATCH")
            assert body["model_bundle_demo_ready"] is False


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
