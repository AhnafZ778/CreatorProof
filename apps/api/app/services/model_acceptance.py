from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from app.services.benchmark_manifest import validate_benchmark_report_payload
from app.services.model_bundle import canonical_json_digest

ACCEPTANCE_POLICY_SCHEMA = "creatorproof.model_acceptance_policy.v1"
RATIFICATION_STATES = {"DRAFT_NOT_RATIFIED", "RATIFIED_BEFORE_FINAL_TEST"}
OPERATORS = {"EQ", "GTE", "LTE"}


@dataclass(frozen=True, slots=True)
class ModelAcceptancePolicy:
    policy_id: str
    domain_id: str
    ratification_state: str
    bundle_id: str
    bundle_manifest_digest_sha256: str
    report_policies: dict[str, dict]
    required_external_gates: tuple[str, ...]
    payload: dict
    digest_sha256: str


def _required_text(payload: dict, key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ValueError(f"acceptance policy {key} is required")
    return value


def _digest(value: object, *, field: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"acceptance policy {field} must be a SHA-256 digest")
    return digest


def load_acceptance_policy(path: Path | str) -> ModelAcceptancePolicy:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read acceptance policy: {type(exc).__name__}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != ACCEPTANCE_POLICY_SCHEMA:
        raise ValueError("unsupported acceptance policy schema")
    policy_id = _required_text(payload, "policy_id")
    domain_id = _required_text(payload, "domain_id")
    ratification_state = _required_text(payload, "ratification_state")
    if ratification_state not in RATIFICATION_STATES:
        raise ValueError("acceptance policy ratification_state is unsupported")
    bundle = payload.get("model_bundle")
    if not isinstance(bundle, dict):
        raise ValueError("acceptance policy model_bundle must be an object")
    bundle_id = _required_text(bundle, "bundle_id")
    bundle_digest = _digest(
        bundle.get("manifest_digest_sha256"),
        field="model_bundle.manifest_digest_sha256",
    )
    raw_report_policies = payload.get("report_policies")
    if not isinstance(raw_report_policies, list) or not raw_report_policies:
        raise ValueError("acceptance policy report_policies must be a non-empty array")
    report_policies: dict[str, dict] = {}
    for index, report_policy in enumerate(raw_report_policies):
        if not isinstance(report_policy, dict):
            raise ValueError(f"acceptance policy report_policies[{index}] must be an object")
        report_schema = _required_text(report_policy, "report_schema")
        if report_schema in report_policies:
            raise ValueError("acceptance policy report_schema values must be unique")
        gates = report_policy.get("gates")
        if not isinstance(gates, list) or not gates:
            raise ValueError(f"acceptance policy {report_schema} gates must be a non-empty array")
        gate_ids: set[str] = set()
        for gate in gates:
            if not isinstance(gate, dict):
                raise ValueError(f"acceptance gate in {report_schema} must be an object")
            gate_id = _required_text(gate, "gate_id")
            if gate_id in gate_ids:
                raise ValueError(f"duplicate acceptance gate id: {gate_id}")
            gate_ids.add(gate_id)
            _required_text(gate, "path")
            operator = _required_text(gate, "operator")
            if operator not in OPERATORS:
                raise ValueError(f"unsupported acceptance operator: {operator}")
            if "value" not in gate:
                raise ValueError(f"acceptance gate {gate_id} value is required")
        report_policies[report_schema] = dict(report_policy)
    external = payload.get("required_external_gates") or []
    if not isinstance(external, list) or not all(
        isinstance(item, str) and item.strip() for item in external
    ):
        raise ValueError("acceptance policy required_external_gates must be strings")
    if payload.get("automatic_promotion_allowed") is not False:
        raise ValueError("acceptance policy must explicitly prohibit automatic promotion")
    final_test = payload.get("final_test_lock")
    if not isinstance(final_test, dict) or final_test.get("required") is not True:
        raise ValueError("acceptance policy must require a locked final test")
    return ModelAcceptancePolicy(
        policy_id=policy_id,
        domain_id=domain_id,
        ratification_state=ratification_state,
        bundle_id=bundle_id,
        bundle_manifest_digest_sha256=bundle_digest,
        report_policies=report_policies,
        required_external_gates=tuple(external),
        payload=payload,
        digest_sha256=canonical_json_digest(payload),
    )


def _resolve_path(payload: dict, path: str):
    current: object = payload
    for segment in path.split("."):
        if not segment or not isinstance(current, dict) or segment not in current:
            raise KeyError(path)
        current = current[segment]
    return current


def _gate_passes(actual: object, operator: str, expected: object) -> bool:
    if operator == "EQ":
        return actual == expected
    if isinstance(actual, bool) or isinstance(expected, bool):
        return False
    try:
        left = float(actual)
        right = float(expected)
    except (TypeError, ValueError):
        return False
    if not math.isfinite(left) or not math.isfinite(right):
        return False
    return left >= right if operator == "GTE" else left <= right


def evaluate_benchmark_acceptance(
    *,
    report: dict,
    policy: ModelAcceptancePolicy,
    external_evidence: dict[str, str] | None = None,
) -> dict:
    validation = validate_benchmark_report_payload(report)
    report_schema = str(report["schema"])
    report_policy = policy.report_policies.get(report_schema)
    failures: list[str] = []
    if report_policy is None:
        failures.append("REPORT_SCHEMA_NOT_COVERED_BY_POLICY")
        gates: list[dict] = []
    else:
        gates = report_policy["gates"]

    run_identity = report["run_identity"]
    if run_identity.get("model_bundle_id") != policy.bundle_id:
        failures.append("MODEL_BUNDLE_ID_MISMATCH")
    if (
        run_identity.get("model_bundle_manifest_digest_sha256")
        != policy.bundle_manifest_digest_sha256
    ):
        failures.append("MODEL_BUNDLE_DIGEST_MISMATCH")
    manifest_domains = {
        str(item.get("domain_id") or "")
        for item in (report.get("corpus_integrity", {}).get("manifests") or [])
    }
    if manifest_domains and manifest_domains != {policy.domain_id}:
        failures.append("DECLARED_DOMAIN_MISMATCH")
    if not report.get("evaluation_eligible"):
        failures.append("REPORT_NOT_EVALUATION_ELIGIBLE")
    if policy.ratification_state != "RATIFIED_BEFORE_FINAL_TEST":
        failures.append("ACCEPTANCE_POLICY_NOT_RATIFIED_BEFORE_FINAL_TEST")

    gate_results: list[dict] = []
    for gate in gates:
        try:
            actual = _resolve_path(report, str(gate["path"]))
            passed = _gate_passes(actual, str(gate["operator"]), gate["value"])
            reason = None if passed else "ACCEPTANCE_GATE_FAILED"
        except KeyError:
            actual = None
            passed = False
            reason = "ACCEPTANCE_METRIC_MISSING"
        gate_results.append(
            {
                "gate_id": gate["gate_id"],
                "path": gate["path"],
                "operator": gate["operator"],
                "expected": gate["value"],
                "actual": actual,
                "passed": passed,
                "reason_code": reason,
            }
        )
        if not passed:
            failures.append(f"METRIC_GATE_FAILED:{gate['gate_id']}")

    supplied_external = external_evidence or {}
    external_results = [
        {
            "gate_id": gate_id,
            "evidence_reference": supplied_external.get(gate_id),
            "passed": bool(str(supplied_external.get(gate_id) or "").strip()),
        }
        for gate_id in policy.required_external_gates
    ]
    failures.extend(
        f"EXTERNAL_GATE_UNRESOLVED:{row['gate_id']}"
        for row in external_results
        if not row["passed"]
    )
    metrics_passed = bool(gate_results) and all(row["passed"] for row in gate_results)
    ready_for_human_promotion_review = not failures
    return {
        "schema": "creatorproof.model_acceptance_evaluation.v1",
        "policy_id": policy.policy_id,
        "acceptance_policy_digest_sha256": policy.digest_sha256,
        "report_digest_sha256": validation["report_digest_sha256"],
        "report_schema": report_schema,
        "model_bundle_id": run_identity.get("model_bundle_id"),
        "model_bundle_manifest_digest_sha256": run_identity.get(
            "model_bundle_manifest_digest_sha256"
        ),
        "metrics_passed": metrics_passed,
        "gate_results": gate_results,
        "external_gate_results": external_results,
        "ready_for_human_promotion_review": ready_for_human_promotion_review,
        "automatic_promotion_performed": False,
        "recommendation": (
            "METRIC_AND_EXTERNAL_GATES_PASSED_REQUIRES_HUMAN_PROMOTION_RECORD"
            if ready_for_human_promotion_review
            else "DO_NOT_PROMOTE"
        ),
        "reason_codes": sorted(set(failures)),
    }
