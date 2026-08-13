from copy import deepcopy

import pytest

from app.services.benchmark_manifest import (
    benchmark_run_identity,
    seal_benchmark_report,
    validate_benchmark_report_payload,
)
from app.services.model_bundle import load_model_bundle


def _report():
    bundle = load_model_bundle(
        "model_lab/bundles/creatorproof-runtime-ready-v1.json",
        strict=True,
    )
    rows = [{"asset_id": "a", "prediction": "NO_MATCH"}]
    return seal_benchmark_report(
        {
            "schema": "creatorproof.copy_benchmark.v2",
            "run_identity": benchmark_run_identity(
                lane="COPY",
                manifest_payload={"manifest_id": "test"},
                model_bundle=bundle,
                threshold_policy_id="copy-v1",
            ),
            "evaluation_grade": "SMOKE_TEST_ONLY",
            "evaluation_eligible": False,
            "promotion_eligible": False,
            "promotion_decision": {
                "state": "NOT_EVALUATED",
                "reason_code": "SMOKE_TEST_ONLY",
                "acceptance_policy_digest_sha256": None,
            },
            "minimum_support_gate": {"positive_pairs": 20, "negative_pairs": 20},
            "operating_configuration": {"fusion_policy_id": "copy-v1"},
            "corpus_integrity": {
                "state": "LEGACY_UNVALIDATED_MANIFEST",
                "evaluation_eligible": False,
                "promotion_eligible": False,
            },
            "records": rows,
            "warning": "Test-only report; no accuracy claim.",
        }
    )


def test_benchmark_report_validator_emits_canonical_report_digest():
    result = validate_benchmark_report_payload(_report())

    assert result["valid"] is True
    assert result["evaluation_grade"] == "SMOKE_TEST_ONLY"
    assert len(result["report_digest_sha256"]) == 64


def test_benchmark_report_validator_rejects_tampered_run_identity():
    report = deepcopy(_report())
    report["run_identity"]["threshold_policy_id"] = "changed-after-run"

    with pytest.raises(ValueError, match="identity digest"):
        validate_benchmark_report_payload(report)


def test_smoke_test_report_cannot_be_evaluation_eligible():
    report = _report()
    report["evaluation_eligible"] = True
    report = seal_benchmark_report(report)

    with pytest.raises(ValueError, match="smoke-test"):
        validate_benchmark_report_payload(report)


def test_benchmark_report_validator_rejects_tampered_predictions():
    report = _report()
    report["records"][0]["prediction"] = "MATCH_FOUND"

    with pytest.raises(ValueError, match="prediction digest"):
        validate_benchmark_report_payload(report)


def test_benchmark_report_validator_rejects_tampered_metric_inputs():
    report = _report()
    report["operating_configuration"]["fusion_policy_id"] = "changed"

    with pytest.raises(ValueError, match="metric inputs digest"):
        validate_benchmark_report_payload(report)


def test_benchmark_report_validator_rejects_tampered_metric_output():
    report = _report()
    report["recall"] = 1.0

    with pytest.raises(ValueError, match="report digest"):
        validate_benchmark_report_payload(report)


def test_model_promotion_requires_acceptance_policy_digest():
    report = _report()
    report["evaluation_grade"] = "HELD_OUT_EVALUATION"
    report["evaluation_eligible"] = True
    report["promotion_eligible"] = True
    report["promotion_decision"] = {
        "state": "PROMOTED_FOR_DECLARED_DOMAIN",
        "reason_code": "ALL_GATES_PASSED",
        "acceptance_policy_digest_sha256": None,
    }
    report["corpus_integrity"] = {
        "state": "VALID_TEST_CORPUS_BINDING",
        "evaluation_eligible": True,
        "promotion_eligible": False,
        "manifest_set_digest_sha256": report["run_identity"].get(
            "corpus_manifest_set_digest_sha256"
        ),
    }
    report = seal_benchmark_report(report)

    with pytest.raises(ValueError, match="acceptance policy"):
        validate_benchmark_report_payload(report)


def test_checked_in_structural_manifest_examples_are_leakage_free():
    from pathlib import Path

    from app.services.benchmark_manifest import load_corpus_manifest, validate_manifest_set

    root = Path("benchmarks/manifests/examples")
    result = validate_manifest_set(
        [
            load_corpus_manifest(root / "copy-calibration.structural.v1.json"),
            load_corpus_manifest(root / "copy-test.structural.v1.json"),
        ]
    )

    assert result["valid"] is True
    assert result["partitions"] == ["CALIBRATION", "TEST"]
