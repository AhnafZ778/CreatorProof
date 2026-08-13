from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MODEL_BUNDLE_SCHEMA = "creatorproof.model_bundle.v1"
QUALIFICATION_STATES = (
    "SOURCE_VERIFIED",
    "RUNTIME_READY",
    "SMOKE_TEST_ONLY",
    "DEMO_READY",
    "CALIBRATED_DOMAIN_READY",
    "PRODUCTION_READY",
)
TERMS_STATES = (
    "RESOLVED",
    "REVIEW_REQUIRED",
    "RESEARCH_ONLY",
    "NOT_APPLICABLE",
)
_QUALIFICATION_RANK = {state: index for index, state in enumerate(QUALIFICATION_STATES)}


def canonical_json_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_tree_revision(root: Path) -> str:
    root = Path(root)
    files: set[Path] = set()
    for pattern in ("app/**/*.py", "scripts/**/*.py"):
        files.update(path for path in root.glob(pattern) if path.is_file())
    files.update(path for path in (root / "pyproject.toml",) if path.is_file())
    records = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": file_sha256(path),
        }
        for path in sorted(files)
    ]
    return f"creatorproof-source-tree-sha256:{canonical_json_digest(records)}"


def _sha256_or_none(value: object) -> str | None:
    if value in (None, ""):
        return None
    digest = str(value).strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError("artifact_sha256 must be a lowercase SHA-256 hex digest")
    return digest


def _safe_relative_path(value: object, *, field_name: str) -> str:
    path_text = str(value or "").strip()
    path = Path(path_text)
    if not path_text or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{field_name} must be a safe relative path")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class RuntimeEnvironment:
    python_major_minor: str
    observed_python: str
    packages: tuple[tuple[str, str], ...]
    requirement_file_digests: tuple[tuple[str, str], ...]

    @classmethod
    def from_payload(cls, payload: object, *, required: bool) -> RuntimeEnvironment | None:
        if payload in (None, {}):
            if required:
                raise ValueError(
                    "runtime_environment is required for RUNTIME_READY or higher bundles"
                )
            return None
        if not isinstance(payload, dict):
            raise ValueError("runtime_environment must be an object")

        python_major_minor = str(payload.get("python_major_minor") or "").strip()
        version_parts = python_major_minor.split(".")
        if len(version_parts) != 2 or not all(part.isdigit() for part in version_parts):
            raise ValueError("runtime_environment.python_major_minor must use MAJOR.MINOR")
        observed_python = str(payload.get("observed_python") or "").strip()
        if not observed_python:
            raise ValueError("runtime_environment.observed_python is required")

        packages_payload = payload.get("packages")
        if not isinstance(packages_payload, dict) or not packages_payload:
            raise ValueError("runtime_environment.packages must be a non-empty object")
        packages: list[tuple[str, str]] = []
        for package_name, version in packages_payload.items():
            normalized_name = str(package_name or "").strip().lower()
            normalized_version = str(version or "").strip()
            if not normalized_name or not normalized_version:
                raise ValueError("runtime package names and versions must be non-empty")
            packages.append((normalized_name, normalized_version))

        requirements_payload = payload.get("requirement_file_digests")
        if not isinstance(requirements_payload, dict) or not requirements_payload:
            raise ValueError(
                "runtime_environment.requirement_file_digests must be a non-empty object"
            )
        requirement_file_digests: list[tuple[str, str]] = []
        for requirement_path, digest_value in requirements_payload.items():
            safe_path = _safe_relative_path(
                requirement_path,
                field_name="runtime requirement file",
            )
            digest = _sha256_or_none(digest_value)
            if digest is None:
                raise ValueError(f"runtime requirement file {safe_path} requires a digest")
            requirement_file_digests.append((safe_path, digest))

        return cls(
            python_major_minor=python_major_minor,
            observed_python=observed_python,
            packages=tuple(sorted(packages)),
            requirement_file_digests=tuple(sorted(requirement_file_digests)),
        )

    def public_record(self) -> dict:
        return {
            "python_major_minor": self.python_major_minor,
            "observed_python": self.observed_python,
            "packages": dict(self.packages),
            "requirement_file_digests": dict(self.requirement_file_digests),
        }


@dataclass(frozen=True, slots=True)
class ModelComponent:
    component_id: str
    role: str
    provider_id: str
    model_version: str
    preprocessing_id: str
    qualification_state: str
    terms_state: str
    source_revision: str
    artifact_required: bool
    artifact_sha256: str | None
    required_for_demo: bool
    limitations: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: dict) -> ModelComponent:
        required_text = (
            "component_id",
            "role",
            "provider_id",
            "model_version",
            "preprocessing_id",
            "qualification_state",
            "terms_state",
            "source_revision",
        )
        missing = [key for key in required_text if not str(payload.get(key) or "").strip()]
        if missing:
            raise ValueError(f"component missing required fields: {','.join(missing)}")
        qualification_state = str(payload["qualification_state"])
        if qualification_state not in QUALIFICATION_STATES:
            raise ValueError(f"unsupported component qualification state: {qualification_state}")
        terms_state = str(payload["terms_state"])
        if terms_state not in TERMS_STATES:
            raise ValueError(f"unsupported component terms state: {terms_state}")
        artifact_required = bool(payload.get("artifact_required", False))
        artifact_sha256 = _sha256_or_none(payload.get("artifact_sha256"))
        if (
            artifact_required
            and _QUALIFICATION_RANK[qualification_state] >= _QUALIFICATION_RANK["RUNTIME_READY"]
            and artifact_sha256 is None
        ):
            raise ValueError(
                f"component {payload['component_id']} requires an artifact digest at "
                f"{qualification_state}"
            )
        limitations = payload.get("limitations") or []
        if not isinstance(limitations, list) or not all(
            isinstance(item, str) and item.strip() for item in limitations
        ):
            raise ValueError("component limitations must be a list of non-empty strings")
        return cls(
            component_id=str(payload["component_id"]),
            role=str(payload["role"]),
            provider_id=str(payload["provider_id"]),
            model_version=str(payload["model_version"]),
            preprocessing_id=str(payload["preprocessing_id"]),
            qualification_state=qualification_state,
            terms_state=terms_state,
            source_revision=str(payload["source_revision"]),
            artifact_required=artifact_required,
            artifact_sha256=artifact_sha256,
            required_for_demo=bool(payload.get("required_for_demo", False)),
            limitations=tuple(limitations),
        )

    def public_record(self) -> dict:
        return {
            "component_id": self.component_id,
            "role": self.role,
            "provider_id": self.provider_id,
            "model_version": self.model_version,
            "preprocessing_id": self.preprocessing_id,
            "qualification_state": self.qualification_state,
            "terms_state": self.terms_state,
            "source_revision": self.source_revision,
            "artifact_required": self.artifact_required,
            "artifact_sha256": self.artifact_sha256,
            "required_for_demo": self.required_for_demo,
            "limitations": list(self.limitations),
        }


@dataclass(frozen=True, slots=True)
class ModelBundle:
    manifest_state: str
    bundle_id: str
    qualification_state: str
    application_revision: str
    runtime_lock_digest: str | None
    runtime_environment: RuntimeEnvironment | None
    domain_id: str
    manifest_path: str
    manifest_digest_sha256: str | None
    components: tuple[ModelComponent, ...]
    limitations: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @classmethod
    def unavailable(cls, path: Path, reason_code: str) -> ModelBundle:
        return cls(
            manifest_state="NOT_CONFIGURED",
            bundle_id="creatorproof-model-bundle-unavailable",
            qualification_state="SOURCE_VERIFIED",
            application_revision="UNKNOWN",
            runtime_lock_digest=None,
            runtime_environment=None,
            domain_id="UNDECLARED",
            manifest_path=str(path),
            manifest_digest_sha256=None,
            components=(),
            limitations=(
                "No validated ModelBundle manifest is active; runtime provider status remains "
                "visible but cannot support a promoted model claim.",
            ),
            reason_codes=(reason_code,),
        )

    def component(self, component_id: str) -> ModelComponent | None:
        return next(
            (component for component in self.components if component.component_id == component_id),
            None,
        )

    def declared_artifact_sha256(self, component_id: str) -> str:
        component = self.component(component_id)
        return component.artifact_sha256 if component and component.artifact_sha256 else ""

    def status(self) -> dict:
        return {
            "manifest_state": self.manifest_state,
            "bundle_id": self.bundle_id,
            "qualification_state": self.qualification_state,
            "manifest_path": self.manifest_path,
            "manifest_digest_sha256": self.manifest_digest_sha256,
            "domain_id": self.domain_id,
            "reason_codes": list(self.reason_codes),
        }

    def packet_record(self, *, runtime: dict | None = None) -> dict:
        return {
            "bundle_id": self.bundle_id,
            "manifest_state": self.manifest_state,
            "qualification_state": self.qualification_state,
            "artifact_manifest_digest": self.manifest_digest_sha256,
            "application_revision": self.application_revision,
            "runtime_lock_digest": self.runtime_lock_digest,
            "runtime_environment": (
                self.runtime_environment.public_record() if self.runtime_environment else None
            ),
            "domain_id": self.domain_id,
            "components": [component.public_record() for component in self.components],
            "limitations": list(self.limitations),
            "reason_codes": list(self.reason_codes),
            "runtime": runtime or {},
        }


def _parse_bundle(path: Path, payload: dict) -> ModelBundle:
    if payload.get("schema") != MODEL_BUNDLE_SCHEMA:
        raise ValueError("unsupported ModelBundle schema")
    required_text = ("bundle_id", "qualification_state", "application_revision", "domain_id")
    missing = [key for key in required_text if not str(payload.get(key) or "").strip()]
    if missing:
        raise ValueError(f"bundle missing required fields: {','.join(missing)}")
    qualification_state = str(payload["qualification_state"])
    if qualification_state not in QUALIFICATION_STATES:
        raise ValueError(f"unsupported bundle qualification state: {qualification_state}")
    runtime_lock_digest = _sha256_or_none(payload.get("runtime_lock_digest"))
    bundle_rank = _QUALIFICATION_RANK[qualification_state]
    runtime_environment = RuntimeEnvironment.from_payload(
        payload.get("runtime_environment"),
        required=bundle_rank >= _QUALIFICATION_RANK["RUNTIME_READY"],
    )
    components_payload = payload.get("components")
    if not isinstance(components_payload, list) or not components_payload:
        raise ValueError("bundle components must be a non-empty array")
    components = tuple(ModelComponent.from_payload(item) for item in components_payload)
    component_ids = [component.component_id for component in components]
    if len(component_ids) != len(set(component_ids)):
        raise ValueError("bundle component_id values must be unique")
    for component in components:
        if not component.required_for_demo:
            continue
        if _QUALIFICATION_RANK[component.qualification_state] < bundle_rank:
            raise ValueError(
                f"required component {component.component_id} is below bundle qualification "
                f"state {qualification_state}"
            )
        if bundle_rank >= _QUALIFICATION_RANK["DEMO_READY"] and component.terms_state not in {
            "RESOLVED",
            "NOT_APPLICABLE",
        }:
            raise ValueError(
                f"required component {component.component_id} has unresolved demo terms"
            )
    limitations = payload.get("limitations") or []
    if not isinstance(limitations, list) or not all(
        isinstance(item, str) and item.strip() for item in limitations
    ):
        raise ValueError("bundle limitations must be a list of non-empty strings")
    return ModelBundle(
        manifest_state="VALID",
        bundle_id=str(payload["bundle_id"]),
        qualification_state=qualification_state,
        application_revision=str(payload["application_revision"]),
        runtime_lock_digest=runtime_lock_digest,
        runtime_environment=runtime_environment,
        domain_id=str(payload["domain_id"]),
        manifest_path=str(path),
        manifest_digest_sha256=canonical_json_digest(payload),
        components=components,
        limitations=tuple(limitations),
        reason_codes=(),
    )


def load_model_bundle(path: Path, *, strict: bool = False) -> ModelBundle:
    path = Path(path)
    if not path.is_file():
        if strict:
            raise ValueError(f"ModelBundle manifest not found: {path}")
        return ModelBundle.unavailable(path, "MODEL_BUNDLE_MANIFEST_NOT_FOUND")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("ModelBundle manifest must be a JSON object")
        return _parse_bundle(path, payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if strict:
            raise ValueError(f"Invalid ModelBundle manifest: {type(exc).__name__}: {exc}") from exc
        return ModelBundle.unavailable(path, f"MODEL_BUNDLE_INVALID:{type(exc).__name__}")


def validate_model_bundle_runtime(
    bundle: ModelBundle,
    *,
    runtime_lock_path: Path,
    artifact_paths: dict[str, Path],
    application_root: Path = Path("."),
    include_optional_artifacts: bool = True,
) -> dict:
    lock_path = Path(runtime_lock_path)
    lock_actual = file_sha256(lock_path) if lock_path.is_file() else None
    lock_matches = bool(
        lock_actual and bundle.runtime_lock_digest and lock_actual == bundle.runtime_lock_digest
    )
    runtime_environment = bundle.runtime_environment
    actual_python = platform.python_version()
    actual_python_major_minor = ".".join(platform.python_version_tuple()[:2])
    package_rows: list[dict] = []
    requirement_rows: list[dict] = []
    if runtime_environment:
        for package_name, expected_version in runtime_environment.packages:
            try:
                actual_version = importlib.metadata.version(package_name)
            except importlib.metadata.PackageNotFoundError:
                actual_version = None
            package_rows.append(
                {
                    "package": package_name,
                    "expected_version": expected_version,
                    "actual_version": actual_version,
                    "matches": actual_version == expected_version,
                }
            )
        for relative_path, expected_digest in runtime_environment.requirement_file_digests:
            requirement_path = Path(application_root) / relative_path
            actual_digest = file_sha256(requirement_path) if requirement_path.is_file() else None
            requirement_rows.append(
                {
                    "path": relative_path,
                    "expected_sha256": expected_digest,
                    "actual_sha256": actual_digest,
                    "matches": actual_digest == expected_digest,
                }
            )
    environment_configured = runtime_environment is not None
    environment_matches = bool(
        runtime_environment
        and actual_python_major_minor == runtime_environment.python_major_minor
        and actual_python == runtime_environment.observed_python
        and package_rows
        and all(row["matches"] for row in package_rows)
        and requirement_rows
        and all(row["matches"] for row in requirement_rows)
    )
    component_rows: list[dict] = []
    for component in bundle.components:
        configured_path = artifact_paths.get(component.component_id)
        artifact_path: Path | None = None
        resolution_reason = None
        should_validate_artifact = bool(component.required_for_demo or include_optional_artifacts)
        if configured_path is not None and should_validate_artifact:
            configured_path = Path(configured_path)
            if configured_path.is_dir():
                candidates = sorted(configured_path.glob("*.safetensors"))
                if len(candidates) == 1:
                    artifact_path = candidates[0]
                else:
                    resolution_reason = f"EXPECTED_ONE_SAFETENSORS_FOUND_{len(candidates)}"
            elif configured_path.is_file():
                artifact_path = configured_path
            else:
                resolution_reason = "ARTIFACT_PATH_NOT_FOUND"

        actual_sha256 = file_sha256(artifact_path) if artifact_path is not None else None
        if not component.artifact_required:
            artifact_state = "NOT_FILE_BACKED"
        elif not should_validate_artifact:
            artifact_state = "NOT_VALIDATED_OPTIONAL"
        elif actual_sha256 is None:
            artifact_state = "UNAVAILABLE"
        elif component.artifact_sha256 is None:
            artifact_state = "UNPINNED_ARTIFACT"
        elif actual_sha256 != component.artifact_sha256:
            artifact_state = "HASH_MISMATCH"
        else:
            artifact_state = "VERIFIED"
        component_rows.append(
            {
                **component.public_record(),
                "configured_artifact_path": (
                    str(configured_path) if configured_path is not None else None
                ),
                "resolved_artifact_path": str(artifact_path) if artifact_path else None,
                "actual_artifact_sha256": actual_sha256,
                "artifact_state": artifact_state,
                "resolution_reason": resolution_reason,
            }
        )

    bundle_rank = _QUALIFICATION_RANK.get(bundle.qualification_state, 0)
    actual_application_revision = source_tree_revision(application_root)
    application_revision_matches = actual_application_revision == bundle.application_revision
    required_rows = [row for row in component_rows if row["required_for_demo"]]
    runtime_artifact_failures = [
        row["component_id"]
        for row in required_rows
        if row["artifact_required"] and row["artifact_state"] != "VERIFIED"
    ]
    terms_failures = [
        row["component_id"]
        for row in required_rows
        if row["terms_state"] not in {"RESOLVED", "NOT_APPLICABLE"}
    ]
    component_state_failures = [
        row["component_id"]
        for row in required_rows
        if _QUALIFICATION_RANK[row["qualification_state"]] < bundle_rank
    ]
    runtime_requirement_met = bool(
        bundle.manifest_state == "VALID"
        and lock_matches
        and (bundle_rank < _QUALIFICATION_RANK["RUNTIME_READY"] or application_revision_matches)
        and (bundle_rank < _QUALIFICATION_RANK["RUNTIME_READY"] or environment_matches)
        and (bundle_rank < _QUALIFICATION_RANK["RUNTIME_READY"] or not runtime_artifact_failures)
        and (bundle_rank < _QUALIFICATION_RANK["DEMO_READY"] or not terms_failures)
        and not component_state_failures
    )
    return {
        "schema": "creatorproof.model_bundle_runtime_validation.v1",
        "bundle": bundle.status(),
        "runtime_lock": {
            "path": str(lock_path),
            "expected_sha256": bundle.runtime_lock_digest,
            "actual_sha256": lock_actual,
            "matches": lock_matches,
        },
        "application_revision": {
            "expected": bundle.application_revision,
            "actual": actual_application_revision,
            "matches": application_revision_matches,
        },
        "runtime_environment": {
            "configured": environment_configured,
            "expected_python_major_minor": (
                runtime_environment.python_major_minor if runtime_environment else None
            ),
            "actual_python_major_minor": actual_python_major_minor,
            "expected_python": runtime_environment.observed_python if runtime_environment else None,
            "actual_python": actual_python,
            "packages": package_rows,
            "requirement_files": requirement_rows,
            "matches": environment_matches,
        },
        "components": component_rows,
        "runtime_artifact_failures": runtime_artifact_failures,
        "terms_failures": terms_failures,
        "component_state_failures": component_state_failures,
        "runtime_requirement_met_for_declared_state": runtime_requirement_met,
        "demo_ready": bool(
            runtime_requirement_met and bundle_rank >= _QUALIFICATION_RANK["DEMO_READY"]
        ),
    }
