import importlib.metadata
import json
import platform
from pathlib import Path

import pytest

from app.services.model_bundle import (
    canonical_json_digest,
    file_sha256,
    load_model_bundle,
    source_tree_revision,
    validate_model_bundle_runtime,
)


def _component(**overrides) -> dict:
    payload = {
        "component_id": "copy-retrieval",
        "role": "COPY_CANDIDATE_RETRIEVAL",
        "provider_id": "test-provider",
        "model_version": "v1",
        "preprocessing_id": "test-preprocess-v1",
        "qualification_state": "SOURCE_VERIFIED",
        "terms_state": "RESOLVED",
        "source_revision": "commit-123",
        "artifact_required": True,
        "artifact_sha256": None,
        "required_for_demo": True,
        "limitations": ["Test-only component."],
    }
    payload.update(overrides)
    return payload


def _bundle(**overrides) -> dict:
    payload = {
        "schema": "creatorproof.model_bundle.v1",
        "bundle_id": "test-bundle-v1",
        "qualification_state": "SOURCE_VERIFIED",
        "application_revision": "test-revision",
        "runtime_lock_digest": "a" * 64,
        "domain_id": "TEST_DOMAIN",
        "components": [_component()],
        "limitations": ["Test-only bundle."],
    }
    payload.update(overrides)
    return payload


def _runtime_environment(tmp_path: Path) -> dict:
    requirements = tmp_path / "requirements-test.txt"
    requirements.write_text("pytest runtime identity\n", encoding="utf-8")
    return {
        "python_major_minor": ".".join(platform.python_version_tuple()[:2]),
        "observed_python": platform.python_version(),
        "packages": {"pytest": importlib.metadata.version("pytest")},
        "requirement_file_digests": {
            requirements.name: file_sha256(requirements),
        },
    }


def test_valid_bundle_has_stable_canonical_identity(tmp_path):
    payload = _bundle()
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    bundle = load_model_bundle(path, strict=True)

    assert bundle.manifest_state == "VALID"
    assert bundle.bundle_id == "test-bundle-v1"
    assert bundle.manifest_digest_sha256 == canonical_json_digest(payload)
    assert bundle.component("copy-retrieval").provider_id == "test-provider"
    assert bundle.declared_artifact_sha256("copy-retrieval") == ""


def test_promoted_artifact_component_requires_a_digest(tmp_path):
    payload = _bundle(
        components=[_component(qualification_state="RUNTIME_READY", artifact_sha256=None)]
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="requires an artifact digest"):
        load_model_bundle(path, strict=True)


def test_duplicate_component_identity_is_rejected(tmp_path):
    payload = _bundle(components=[_component(), _component()])
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="must be unique"):
        load_model_bundle(path, strict=True)


def test_non_strict_missing_bundle_is_fail_visible(tmp_path):
    missing = tmp_path / "missing.json"

    bundle = load_model_bundle(missing, strict=False)

    assert bundle.manifest_state == "NOT_CONFIGURED"
    assert bundle.manifest_digest_sha256 is None
    assert bundle.reason_codes == ("MODEL_BUNDLE_MANIFEST_NOT_FOUND",)


def test_default_runtime_ready_bundle_is_valid():
    bundle = load_model_bundle(
        Path("model_lab/bundles/creatorproof-runtime-ready-v1.json"),
        strict=True,
    )

    assert bundle.qualification_state == "RUNTIME_READY"
    assert bundle.component("copy-retrieval-sscd") is not None
    assert bundle.component("origin-community-forensics") is not None
    sightengine = bundle.component("origin-sightengine-genai")
    assert sightengine is not None
    assert sightengine.provider_id == "sightengine-genai"
    assert sightengine.qualification_state == "SOURCE_VERIFIED"
    assert sightengine.artifact_required is False
    assert bundle.component("style-csd") is not None
    assert bundle.runtime_environment is not None
    assert dict(bundle.runtime_environment.packages)["torch"] == "2.13.0"


def test_runtime_ready_bundle_requires_environment_identity(tmp_path):
    payload = _bundle(
        qualification_state="RUNTIME_READY",
        components=[
            _component(
                qualification_state="RUNTIME_READY",
                artifact_sha256="a" * 64,
            )
        ],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="runtime_environment is required"):
        load_model_bundle(path, strict=True)


def test_runtime_environment_rejects_requirement_path_traversal(tmp_path):
    runtime_environment = _runtime_environment(tmp_path)
    runtime_environment["requirement_file_digests"] = {"../outside.txt": "d" * 64}
    payload = _bundle(
        qualification_state="RUNTIME_READY",
        runtime_environment=runtime_environment,
        components=[
            _component(
                qualification_state="RUNTIME_READY",
                artifact_sha256="a" * 64,
            )
        ],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="safe relative path"):
        load_model_bundle(path, strict=True)


def test_runtime_validation_binds_lock_and_artifact_bytes(tmp_path):
    lock = tmp_path / "uv.lock"
    artifact = tmp_path / "model.pt"
    lock.write_text("locked-runtime", encoding="utf-8")
    artifact.write_bytes(b"exact-model-bytes")
    payload = _bundle(
        qualification_state="RUNTIME_READY",
        application_revision=source_tree_revision(tmp_path),
        runtime_lock_digest=file_sha256(lock),
        runtime_environment=_runtime_environment(tmp_path),
        components=[
            _component(
                qualification_state="RUNTIME_READY",
                artifact_sha256=file_sha256(artifact),
            )
        ],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = validate_model_bundle_runtime(
        load_model_bundle(path, strict=True),
        runtime_lock_path=lock,
        artifact_paths={"copy-retrieval": artifact},
        application_root=tmp_path,
    )

    assert report["runtime_requirement_met_for_declared_state"] is True
    assert report["runtime_environment"]["matches"] is True
    assert report["components"][0]["artifact_state"] == "VERIFIED"


def test_runtime_validation_reports_hash_mismatch(tmp_path):
    lock = tmp_path / "uv.lock"
    artifact = tmp_path / "model.pt"
    lock.write_text("locked-runtime", encoding="utf-8")
    artifact.write_bytes(b"wrong-model-bytes")
    payload = _bundle(
        qualification_state="RUNTIME_READY",
        application_revision=source_tree_revision(tmp_path),
        runtime_lock_digest=file_sha256(lock),
        runtime_environment=_runtime_environment(tmp_path),
        components=[
            _component(
                qualification_state="RUNTIME_READY",
                artifact_sha256="b" * 64,
            )
        ],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = validate_model_bundle_runtime(
        load_model_bundle(path, strict=True),
        runtime_lock_path=lock,
        artifact_paths={"copy-retrieval": artifact},
        application_root=tmp_path,
    )

    assert report["runtime_requirement_met_for_declared_state"] is False
    assert report["runtime_artifact_failures"] == ["copy-retrieval"]
    assert report["components"][0]["artifact_state"] == "HASH_MISMATCH"


def test_runtime_validation_rejects_package_version_drift(tmp_path):
    lock = tmp_path / "uv.lock"
    artifact = tmp_path / "model.pt"
    lock.write_text("locked-runtime", encoding="utf-8")
    artifact.write_bytes(b"exact-model-bytes")
    runtime_environment = _runtime_environment(tmp_path)
    runtime_environment["packages"]["pytest"] = "0.0.0-impossible"
    payload = _bundle(
        qualification_state="RUNTIME_READY",
        application_revision=source_tree_revision(tmp_path),
        runtime_lock_digest=file_sha256(lock),
        runtime_environment=runtime_environment,
        components=[
            _component(
                qualification_state="RUNTIME_READY",
                artifact_sha256=file_sha256(artifact),
            )
        ],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = validate_model_bundle_runtime(
        load_model_bundle(path, strict=True),
        runtime_lock_path=lock,
        artifact_paths={"copy-retrieval": artifact},
        application_root=tmp_path,
    )

    assert report["runtime_requirement_met_for_declared_state"] is False
    assert report["runtime_environment"]["matches"] is False
    assert report["runtime_environment"]["packages"][0]["matches"] is False


def test_runtime_validation_rejects_requirement_file_drift(tmp_path):
    lock = tmp_path / "uv.lock"
    artifact = tmp_path / "model.pt"
    lock.write_text("locked-runtime", encoding="utf-8")
    artifact.write_bytes(b"exact-model-bytes")
    runtime_environment = _runtime_environment(tmp_path)
    (tmp_path / "requirements-test.txt").write_text("changed after pinning\n", encoding="utf-8")
    payload = _bundle(
        qualification_state="RUNTIME_READY",
        application_revision=source_tree_revision(tmp_path),
        runtime_lock_digest=file_sha256(lock),
        runtime_environment=runtime_environment,
        components=[
            _component(
                qualification_state="RUNTIME_READY",
                artifact_sha256=file_sha256(artifact),
            )
        ],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    report = validate_model_bundle_runtime(
        load_model_bundle(path, strict=True),
        runtime_lock_path=lock,
        artifact_paths={"copy-retrieval": artifact},
        application_root=tmp_path,
    )

    assert report["runtime_requirement_met_for_declared_state"] is False
    assert report["runtime_environment"]["matches"] is False
    assert report["runtime_environment"]["requirement_files"][0]["matches"] is False


def test_demo_ready_bundle_rejects_unresolved_required_terms(tmp_path):
    payload = _bundle(
        qualification_state="DEMO_READY",
        runtime_environment=_runtime_environment(tmp_path),
        components=[
            _component(
                qualification_state="DEMO_READY",
                artifact_sha256="c" * 64,
                terms_state="REVIEW_REQUIRED",
            )
        ],
    )
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unresolved demo terms"):
        load_model_bundle(path, strict=True)


def test_source_tree_revision_changes_with_runtime_source(tmp_path):
    source = tmp_path / "app" / "service.py"
    source.parent.mkdir()
    source.write_text("VALUE = 1\n", encoding="utf-8")
    first = source_tree_revision(tmp_path)

    source.write_text("VALUE = 2\n", encoding="utf-8")
    second = source_tree_revision(tmp_path)

    assert first.startswith("creatorproof-source-tree-sha256:")
    assert first != second
