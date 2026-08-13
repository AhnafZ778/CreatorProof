from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from app.services.model_bundle import ModelBundle, canonical_json_digest

CORPUS_MANIFEST_SCHEMA = "creatorproof.corpus_manifest.v1"
BENCHMARK_REPORT_SCHEMA = "creatorproof.benchmark_report_contract.v2"
LANES = ("COPY", "AI_ORIGIN", "CREATOR_PROFILE")
PARTITIONS = ("TRAIN", "CALIBRATION", "TEST", "DEMO")
EXPOSURE_STATES = ("NEVER_SEEN", "CALIBRATION_SEEN", "DEMO_EXPOSED")
RIGHTS_STATES = ("OWNED", "AUTHORIZED", "LICENSED", "PUBLIC_DOMAIN_VERIFIED")
PROMOTION_DECISIONS = (
    "NOT_EVALUATED",
    "EVALUATED_NOT_ACCEPTED",
    "PROMOTED_FOR_DECLARED_DOMAIN",
)

_PREDICTION_FIELDS = {
    "creatorproof.copy_retrieval_benchmark.v2": "rows",
    "creatorproof.copy_benchmark.v2": "records",
    "creatorproof.synthetic_benchmark.v2": "rows",
    "creatorproof.style_benchmark.v3": "queries",
}


@dataclass(frozen=True, slots=True)
class CorpusItem:
    asset_id: str
    location: str
    sha256: str
    source_lineage_id: str
    rights_state: str
    rights_reference: str
    exposure_state: str
    label: object
    derived_from_asset_id: str | None
    transformation_id: str | None
    profile_id: str | None
    profile_consent_state: str | None
    cohorts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    manifest_id: str
    dataset_id: str
    lane: str
    partition: str
    domain_id: str
    path: Path
    digest_sha256: str
    items: tuple[CorpusItem, ...]
    limitations: tuple[str, ...]

    def identity_record(self) -> dict:
        return {
            "manifest_id": self.manifest_id,
            "dataset_id": self.dataset_id,
            "lane": self.lane,
            "partition": self.partition,
            "domain_id": self.domain_id,
            "manifest_digest_sha256": self.digest_sha256,
            "item_count": len(self.items),
            "limitations": list(self.limitations),
        }


def _required_text(payload: dict, keys: tuple[str, ...], *, scope: str) -> dict[str, str]:
    result = {key: str(payload.get(key) or "").strip() for key in keys}
    missing = [key for key, value in result.items() if not value]
    if missing:
        raise ValueError(f"{scope} missing required fields: {','.join(missing)}")
    return result


def _sha256(value: object, *, scope: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{scope} sha256 must be a lowercase SHA-256 hex digest")
    return digest


def _safe_location(value: str, *, scope: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"{scope} location must be a safe relative artifact path")
    if not normalized or normalized.startswith("."):
        raise ValueError(f"{scope} location must identify an external authorized artifact")
    return normalized


def _parse_item(payload: dict, *, index: int, lane: str) -> CorpusItem:
    scope = f"item[{index}]"
    text = _required_text(
        payload,
        ("asset_id", "location", "source_lineage_id", "exposure_state"),
        scope=scope,
    )
    rights = payload.get("rights")
    if not isinstance(rights, dict):
        raise ValueError(f"{scope} rights must be an object")
    rights_text = _required_text(rights, ("state", "reference"), scope=f"{scope}.rights")
    if rights_text["state"] not in RIGHTS_STATES:
        raise ValueError(f"{scope} rights state is not authorized for evaluation")
    if text["exposure_state"] not in EXPOSURE_STATES:
        raise ValueError(f"{scope} has unsupported exposure_state")
    label = payload.get("label")
    if label is None:
        raise ValueError(f"{scope} label is required")
    derived_from = str(payload.get("derived_from_asset_id") or "").strip() or None
    transformation_id = str(payload.get("transformation_id") or "").strip() or None
    if bool(derived_from) != bool(transformation_id):
        raise ValueError(
            f"{scope} derived_from_asset_id and transformation_id must be declared together"
        )
    profile_id = str(payload.get("profile_id") or "").strip() or None
    profile_consent_state = str(payload.get("profile_consent_state") or "").strip() or None
    if lane == "CREATOR_PROFILE" and profile_id and profile_consent_state != "CONFIRMED":
        raise ValueError(f"{scope} creator-profile asset requires CONFIRMED consent")
    cohorts = payload.get("cohorts") or []
    if not isinstance(cohorts, list) or not all(
        isinstance(item, str) and item.strip() for item in cohorts
    ):
        raise ValueError(f"{scope} cohorts must be a list of non-empty strings")
    return CorpusItem(
        asset_id=text["asset_id"],
        location=_safe_location(text["location"], scope=scope),
        sha256=_sha256(payload.get("sha256"), scope=scope),
        source_lineage_id=text["source_lineage_id"],
        rights_state=rights_text["state"],
        rights_reference=rights_text["reference"],
        exposure_state=text["exposure_state"],
        label=label,
        derived_from_asset_id=derived_from,
        transformation_id=transformation_id,
        profile_id=profile_id,
        profile_consent_state=profile_consent_state,
        cohorts=tuple(cohorts),
    )


def load_corpus_manifest(path: Path) -> CorpusManifest:
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read corpus manifest {path}: {type(exc).__name__}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != CORPUS_MANIFEST_SCHEMA:
        raise ValueError("unsupported corpus manifest schema")
    text = _required_text(
        payload,
        ("manifest_id", "dataset_id", "lane", "partition", "domain_id"),
        scope="manifest",
    )
    if text["lane"] not in LANES:
        raise ValueError(f"unsupported corpus lane: {text['lane']}")
    if text["partition"] not in PARTITIONS:
        raise ValueError(f"unsupported corpus partition: {text['partition']}")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("corpus manifest items must be a non-empty array")
    items = tuple(
        _parse_item(item, index=index, lane=text["lane"])
        for index, item in enumerate(raw_items)
        if isinstance(item, dict)
    )
    if len(items) != len(raw_items):
        raise ValueError("every corpus item must be a JSON object")
    asset_ids = [item.asset_id for item in items]
    hashes = [item.sha256 for item in items]
    if len(asset_ids) != len(set(asset_ids)):
        raise ValueError("asset_id values must be unique within a manifest")
    if len(hashes) != len(set(hashes)):
        raise ValueError("duplicate asset bytes are not allowed within a manifest")
    if text["partition"] == "TEST" and any(item.exposure_state != "NEVER_SEEN" for item in items):
        raise ValueError("final TEST items must have NEVER_SEEN exposure state")
    limitations = payload.get("limitations") or []
    if not isinstance(limitations, list) or not all(
        isinstance(item, str) and item.strip() for item in limitations
    ):
        raise ValueError("manifest limitations must be a list of non-empty strings")
    return CorpusManifest(
        manifest_id=text["manifest_id"],
        dataset_id=text["dataset_id"],
        lane=text["lane"],
        partition=text["partition"],
        domain_id=text["domain_id"],
        path=path,
        digest_sha256=canonical_json_digest(payload),
        items=items,
        limitations=tuple(limitations),
    )


def validate_manifest_set(manifests: list[CorpusManifest]) -> dict:
    if not manifests:
        raise ValueError("at least one corpus manifest is required")
    manifest_ids = [manifest.manifest_id for manifest in manifests]
    if len(manifest_ids) != len(set(manifest_ids)):
        raise ValueError("manifest_id values must be unique")

    by_hash: dict[str, list[tuple[str, str]]] = {}
    by_lineage: dict[str, list[tuple[str, str]]] = {}
    known_asset_ids: set[str] = set()
    parent_ids: set[str] = set()
    for manifest in manifests:
        for item in manifest.items:
            by_hash.setdefault(item.sha256, []).append((manifest.partition, item.asset_id))
            by_lineage.setdefault(item.source_lineage_id, []).append(
                (manifest.partition, item.asset_id)
            )
            known_asset_ids.add(item.asset_id)
            if item.derived_from_asset_id:
                parent_ids.add(item.derived_from_asset_id)

    for digest, rows in by_hash.items():
        if len({partition for partition, _ in rows}) > 1:
            raise ValueError(f"asset hash leaks across partitions: {digest}")
    for lineage, rows in by_lineage.items():
        if len({partition for partition, _ in rows}) > 1:
            raise ValueError(f"source lineage leaks across partitions: {lineage}")
    missing_parents = sorted(parent_ids - known_asset_ids)
    if missing_parents:
        raise ValueError(f"transformation parents missing from manifest set: {missing_parents}")
    return {
        "valid": True,
        "manifest_count": len(manifests),
        "item_count": sum(len(manifest.items) for manifest in manifests),
        "partitions": sorted({manifest.partition for manifest in manifests}),
        "lanes": sorted({manifest.lane for manifest in manifests}),
        "manifests": [manifest.identity_record() for manifest in manifests],
        "manifest_set_digest_sha256": canonical_json_digest(
            [
                {
                    "manifest_id": manifest.manifest_id,
                    "digest_sha256": manifest.digest_sha256,
                }
                for manifest in sorted(manifests, key=lambda item: item.manifest_id)
            ]
        ),
    }


def bind_benchmark_input_to_corpus(
    *,
    benchmark_manifest_path: Path,
    benchmark_payload: dict,
    lane: str,
    referenced_locations: list[str],
    required_partition: str = "TEST",
) -> dict:
    if lane not in LANES:
        raise ValueError(f"unsupported benchmark lane: {lane}")
    if required_partition not in PARTITIONS:
        raise ValueError(f"unsupported benchmark partition: {required_partition}")
    raw_paths = benchmark_payload.get("corpus_manifest_paths")
    if raw_paths is None:
        return {
            "state": "LEGACY_UNVALIDATED_MANIFEST",
            "evaluation_eligible": False,
            # Deprecated compatibility alias. Corpus binding never promotes a model.
            "promotion_eligible": False,
            "reason_codes": ["CORPUS_MANIFEST_BINDING_NOT_DECLARED"],
            "manifest_set_digest_sha256": None,
        }
    if not isinstance(raw_paths, list) or not raw_paths:
        raise ValueError("corpus_manifest_paths must be a non-empty array")
    root = Path(benchmark_manifest_path).resolve().parent
    paths: list[Path] = []
    for index, raw_path in enumerate(raw_paths):
        normalized = str(raw_path or "").replace("\\", "/")
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError(f"corpus_manifest_paths[{index}] must be a safe relative path")
        paths.append((root / normalized).resolve())
    manifests = [load_corpus_manifest(path) for path in paths]
    validation = validate_manifest_set(manifests)
    wrong_lanes = sorted({manifest.lane for manifest in manifests if manifest.lane != lane})
    if wrong_lanes:
        raise ValueError(f"benchmark corpus lane mismatch: expected {lane}, found {wrong_lanes}")

    locations: dict[str, list[tuple[CorpusManifest, CorpusItem]]] = {}
    for manifest in manifests:
        for item in manifest.items:
            locations.setdefault(item.location, []).append((manifest, item))
    duplicate_locations = sorted(location for location, rows in locations.items() if len(rows) > 1)
    if duplicate_locations:
        raise ValueError(f"corpus locations must be unique: {duplicate_locations}")
    normalized_references = [str(location).replace("\\", "/") for location in referenced_locations]
    missing = sorted(set(normalized_references) - set(locations))
    if missing:
        raise ValueError(f"benchmark assets missing from corpus manifests: {missing}")
    wrong_partition = sorted(
        location
        for location in set(normalized_references)
        if locations[location][0][0].partition != required_partition
    )
    if wrong_partition:
        raise ValueError(f"benchmark assets must belong to {required_partition}: {wrong_partition}")
    return {
        "state": f"VALID_{required_partition}_CORPUS_BINDING",
        "evaluation_eligible": True,
        # Deprecated compatibility alias. A valid corpus makes an evaluation eligible;
        # it does not establish that a model passed an acceptance policy.
        "promotion_eligible": False,
        "reason_codes": [],
        "required_partition": required_partition,
        "referenced_asset_count": len(set(normalized_references)),
        "manifest_set_digest_sha256": validation["manifest_set_digest_sha256"],
        "manifests": validation["manifests"],
        "asset_bindings": [
            {
                "location": location,
                "asset_id": locations[location][0][1].asset_id,
                "source_lineage_id": locations[location][0][1].source_lineage_id,
                "partition": locations[location][0][0].partition,
                "cohorts": list(locations[location][0][1].cohorts),
            }
            for location in sorted(set(normalized_references))
        ],
    }


def corpus_asset_binding(corpus_integrity: dict, location: str) -> dict:
    normalized = str(location).replace("\\", "/")
    for binding in corpus_integrity.get("asset_bindings") or []:
        if binding.get("location") == normalized:
            return dict(binding)
    return {
        "location": normalized,
        "asset_id": None,
        "source_lineage_id": None,
        "partition": None,
        "cohorts": [],
    }


def benchmark_run_identity(
    *,
    lane: str,
    manifest_payload: dict,
    model_bundle: ModelBundle | None,
    threshold_policy_id: str,
    corpus_manifest_set_digest_sha256: str | None = None,
) -> dict:
    if lane not in LANES:
        raise ValueError(f"unsupported benchmark lane: {lane}")
    identity = {
        "lane": lane,
        "manifest_digest_sha256": canonical_json_digest(manifest_payload),
        "corpus_manifest_set_digest_sha256": corpus_manifest_set_digest_sha256,
        "model_bundle_id": model_bundle.bundle_id if model_bundle else None,
        "model_bundle_manifest_digest_sha256": (
            model_bundle.manifest_digest_sha256 if model_bundle else None
        ),
        "model_bundle_qualification_state": (
            model_bundle.qualification_state if model_bundle else None
        ),
        "threshold_policy_id": threshold_policy_id,
        "semantics": "REPRODUCIBLE_RUN_IDENTITY_NOT_ACCURACY_CLAIM",
    }
    return {
        **identity,
        "run_identity_digest_sha256": canonical_json_digest(identity),
    }


def _prediction_field(payload: dict) -> str:
    schema = str(payload.get("schema") or "")
    field = _PREDICTION_FIELDS.get(schema)
    if field is None:
        raise ValueError(f"benchmark report prediction field is unsupported for schema: {schema}")
    return field


def _prediction_records(payload: dict) -> list:
    field = _prediction_field(payload)
    records = payload.get(field)
    if not isinstance(records, list):
        raise ValueError(f"benchmark report {field} must be an array")
    return records


def _metric_input_material(payload: dict) -> dict:
    run_identity = payload.get("run_identity") or {}
    return {
        "prediction_field": _prediction_field(payload),
        "prediction_records": _prediction_records(payload),
        "threshold_policy_id": run_identity.get("threshold_policy_id"),
        "minimum_support_gate": payload.get("minimum_support_gate"),
        "operating_configuration": payload.get("operating_configuration") or {},
    }


def seal_benchmark_report(payload: dict) -> dict:
    """Return a canonical, tamper-sensitive benchmark report.

    The digest is not a signature. Its purpose is to bind prediction rows, metric inputs,
    and the complete report so an independently recorded report digest can detect edits.
    Model promotion remains a separate reviewed decision.
    """

    report = dict(payload)
    report.pop("report_digest_sha256", None)
    records = _prediction_records(report)
    report["prediction_digest_sha256"] = canonical_json_digest(records)
    report["metric_inputs_digest_sha256"] = canonical_json_digest(_metric_input_material(report))
    report["report_digest_sha256"] = canonical_json_digest(report)
    return report


def validate_benchmark_report_payload(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("benchmark report must be a JSON object")
    schema = str(payload.get("schema") or "")
    if not schema.startswith("creatorproof.") or "benchmark" not in schema:
        raise ValueError("benchmark report schema is missing or unsupported")
    run_identity = payload.get("run_identity")
    if not isinstance(run_identity, dict):
        raise ValueError("benchmark report run_identity must be an object")
    required_identity = (
        "lane",
        "manifest_digest_sha256",
        "model_bundle_id",
        "model_bundle_manifest_digest_sha256",
        "model_bundle_qualification_state",
        "threshold_policy_id",
        "run_identity_digest_sha256",
    )
    missing = [key for key in required_identity if not run_identity.get(key)]
    if missing:
        raise ValueError(f"benchmark run identity missing fields: {','.join(missing)}")
    expected_identity_digest = run_identity["run_identity_digest_sha256"]
    identity_material = {
        key: value for key, value in run_identity.items() if key != "run_identity_digest_sha256"
    }
    if canonical_json_digest(identity_material) != expected_identity_digest:
        raise ValueError("benchmark run identity digest does not match its content")
    prediction_digest = _sha256(
        payload.get("prediction_digest_sha256"), scope="benchmark prediction digest"
    )
    if canonical_json_digest(_prediction_records(payload)) != prediction_digest:
        raise ValueError("benchmark prediction digest does not match prediction records")
    metric_inputs_digest = _sha256(
        payload.get("metric_inputs_digest_sha256"), scope="benchmark metric inputs digest"
    )
    if canonical_json_digest(_metric_input_material(payload)) != metric_inputs_digest:
        raise ValueError("benchmark metric inputs digest does not match metric inputs")
    report_digest = _sha256(payload.get("report_digest_sha256"), scope="benchmark report digest")
    report_material = {
        key: value for key, value in payload.items() if key != "report_digest_sha256"
    }
    if canonical_json_digest(report_material) != report_digest:
        raise ValueError("benchmark report digest does not match report content")

    if not isinstance(payload.get("evaluation_eligible"), bool):
        raise ValueError("benchmark evaluation_eligible must be boolean")
    if not isinstance(payload.get("promotion_eligible"), bool):
        raise ValueError("benchmark promotion_eligible compatibility field must be boolean")
    promotion_decision = payload.get("promotion_decision")
    if not isinstance(promotion_decision, dict):
        raise ValueError("benchmark promotion_decision must be an object")
    promotion_state = str(promotion_decision.get("state") or "")
    if promotion_state not in PROMOTION_DECISIONS:
        raise ValueError("benchmark promotion_decision state is unsupported")
    if not str(promotion_decision.get("reason_code") or "").strip():
        raise ValueError("benchmark promotion_decision reason_code is required")
    promoted = promotion_state == "PROMOTED_FOR_DECLARED_DOMAIN"
    if payload["promotion_eligible"] != promoted:
        raise ValueError("benchmark promotion compatibility field disagrees with decision state")
    if promoted and not str(promotion_decision.get("acceptance_policy_digest_sha256") or ""):
        raise ValueError("model promotion requires a bound acceptance policy digest")
    grade = str(payload.get("evaluation_grade") or "")
    if not grade:
        raise ValueError("benchmark evaluation_grade is required")
    if grade == "SMOKE_TEST_ONLY" and payload["evaluation_eligible"]:
        raise ValueError("a smoke-test report cannot be evaluation eligible")
    if not isinstance(payload.get("minimum_support_gate"), dict):
        raise ValueError("benchmark minimum_support_gate must be an object")
    corpus_integrity = payload.get("corpus_integrity")
    if not isinstance(corpus_integrity, dict) or not corpus_integrity.get("state"):
        raise ValueError("benchmark corpus_integrity must declare a state")
    if payload["evaluation_eligible"] and not corpus_integrity.get("evaluation_eligible"):
        raise ValueError("benchmark evaluation requires an eligible corpus binding")
    if promoted and not payload["evaluation_eligible"]:
        raise ValueError("model promotion requires an eligible evaluation")
    if corpus_integrity.get("evaluation_eligible") and (
        run_identity.get("corpus_manifest_set_digest_sha256")
        != corpus_integrity.get("manifest_set_digest_sha256")
    ):
        raise ValueError("benchmark run identity does not bind the validated corpus manifest set")
    if not str(payload.get("warning") or "").strip():
        raise ValueError("benchmark warning/limitation text is required")
    return {
        "schema": BENCHMARK_REPORT_SCHEMA,
        "valid": True,
        "report_schema": schema,
        "run_identity_digest_sha256": expected_identity_digest,
        "prediction_digest_sha256": prediction_digest,
        "metric_inputs_digest_sha256": metric_inputs_digest,
        "report_digest_sha256": report_digest,
        "evaluation_grade": grade,
        "evaluation_eligible": payload["evaluation_eligible"],
        "promotion_eligible": payload["promotion_eligible"],
        "promotion_decision": promotion_state,
        "corpus_integrity_state": corpus_integrity["state"],
    }
