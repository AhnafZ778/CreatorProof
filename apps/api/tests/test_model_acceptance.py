import json

from app.services.benchmark_manifest import benchmark_run_identity, seal_benchmark_report
from app.services.model_acceptance import (
    evaluate_benchmark_acceptance,
    load_acceptance_policy,
)
from app.services.model_bundle import load_model_bundle


def _write_policy(tmp_path, *, ratified: bool = True):
    bundle = load_model_bundle("model_lab/bundles/creatorproof-runtime-ready-v1.json", strict=True)
    payload = {
        "schema": "creatorproof.model_acceptance_policy.v1",
        "policy_id": "test-policy-v1",
        "domain_id": "TEST_DOMAIN",
        "ratification_state": ("RATIFIED_BEFORE_FINAL_TEST" if ratified else "DRAFT_NOT_RATIFIED"),
        "model_bundle": {
            "bundle_id": bundle.bundle_id,
            "manifest_digest_sha256": bundle.manifest_digest_sha256,
        },
        "final_test_lock": {"required": True, "rules": ["Test fixture lock."]},
        "report_policies": [
            {
                "report_schema": "creatorproof.copy_benchmark.v2",
                "gates": [
                    {
                        "gate_id": "test-score",
                        "path": "test_metric.value",
                        "operator": "GTE",
                        "value": 0.8,
                    }
                ],
            }
        ],
        "required_external_gates": [],
        "automatic_promotion_allowed": False,
    }
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_acceptance_policy(path), bundle


def _report(bundle, *, value: float = 0.9):
    corpus_digest = "a" * 64
    return seal_benchmark_report(
        {
            "schema": "creatorproof.copy_benchmark.v2",
            "run_identity": benchmark_run_identity(
                lane="COPY",
                manifest_payload={"manifest_id": "locked-test"},
                model_bundle=bundle,
                threshold_policy_id="test-threshold-v1",
                corpus_manifest_set_digest_sha256=corpus_digest,
            ),
            "evaluation_grade": "HELD_OUT_EVALUATION",
            "evaluation_eligible": True,
            "promotion_eligible": False,
            "promotion_decision": {
                "state": "NOT_EVALUATED",
                "reason_code": "ACCEPTANCE_POLICY_NOT_APPLIED",
                "acceptance_policy_digest_sha256": None,
            },
            "minimum_support_gate": {"positive_pairs": 20, "negative_pairs": 20},
            "operating_configuration": {"fusion_policy_id": "test-threshold-v1"},
            "corpus_integrity": {
                "state": "VALID_TEST_CORPUS_BINDING",
                "evaluation_eligible": True,
                "promotion_eligible": False,
                "manifest_set_digest_sha256": corpus_digest,
                "manifests": [{"domain_id": "TEST_DOMAIN"}],
            },
            "test_metric": {"value": value},
            "records": [{"case": "one", "predicted_match": True}],
            "warning": "Test fixture only.",
        }
    )


def test_passing_policy_can_only_recommend_human_promotion_review(tmp_path):
    policy, bundle = _write_policy(tmp_path)

    result = evaluate_benchmark_acceptance(report=_report(bundle), policy=policy)

    assert result["metrics_passed"] is True
    assert result["ready_for_human_promotion_review"] is True
    assert result["automatic_promotion_performed"] is False
    assert result["recommendation"].endswith("REQUIRES_HUMAN_PROMOTION_RECORD")


def test_failed_metric_blocks_acceptance(tmp_path):
    policy, bundle = _write_policy(tmp_path)

    result = evaluate_benchmark_acceptance(report=_report(bundle, value=0.5), policy=policy)

    assert result["metrics_passed"] is False
    assert result["ready_for_human_promotion_review"] is False
    assert "METRIC_GATE_FAILED:test-score" in result["reason_codes"]


def test_unratified_policy_cannot_be_applied_after_final_test(tmp_path):
    policy, bundle = _write_policy(tmp_path, ratified=False)

    result = evaluate_benchmark_acceptance(report=_report(bundle), policy=policy)

    assert result["metrics_passed"] is True
    assert result["ready_for_human_promotion_review"] is False
    assert "ACCEPTANCE_POLICY_NOT_RATIFIED_BEFORE_FINAL_TEST" in result["reason_codes"]
