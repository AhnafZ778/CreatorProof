from __future__ import annotations

import hashlib
import json
import socket

import pytest

from app.services.benchmark_manifest import load_corpus_manifest, validate_benchmark_report_payload
from scripts.phase1_benchmark import (
    NEGATIVE_GROUPS,
    TRANSFORM_GROUPS,
    generate_dataset,
    run_benchmark,
    summarize,
)


def test_procedural_dataset_is_reproducible_lawful_and_has_all_transform_groups(tmp_path):
    first = generate_dataset(tmp_path / "first", source_count=1, seed=21)
    second = generate_dataset(tmp_path / "second", source_count=1, seed=21)
    payload = json.loads(first.read_text())
    assert payload == json.loads(second.read_text())
    assert set(TRANSFORM_GROUPS + NEGATIVE_GROUPS) <= {case["group"] for case in payload["cases"]}
    assert payload["ai_image_to_image"]["state"] == "UNAVAILABLE"
    assert not any(case["group"] == "AI_IMAGE_TO_IMAGE" for case in payload["cases"])
    corpus = load_corpus_manifest(first.parent / "corpus.json")
    assert corpus.partition == "DEMO"
    assert all(item.rights_state == "AUTHORIZED" for item in corpus.items)
    for item in corpus.items:
        assert (
            hashlib.sha256((first.parent / item.location).read_bytes()).hexdigest() == item.sha256
        )
    exact = next(case for case in payload["cases"] if case["group"] == "EXACT_DUPLICATE")
    assert exact["query"] == exact["reference"]
    negative_hashes = {
        item.sha256
        for item in corpus.items
        if any(group in NEGATIVE_GROUPS for group in item.cohorts)
    }
    assert negative_hashes.isdisjoint(
        {item.sha256 for item in corpus.items if "REFERENCE" in item.cohorts}
    )


def test_ai_fixture_import_requires_authorization_and_generation_record(tmp_path):
    manifest = tmp_path / "unauthorized.json"
    manifest.write_text(
        json.dumps(
            {"cases": [{"query": "q.png", "reference": "r.png", "rights": {"state": "UNKNOWN"}}]}
        )
    )
    with pytest.raises(ValueError, match="explicit authorization"):
        generate_dataset(tmp_path / "invalid", source_count=1, authorized_ai_fixtures=manifest)


def test_benchmark_metrics_use_confusion_counts_and_leave_unmeasured_fields_null():
    rows = []
    for index, (label, predicted) in enumerate(
        [(True, True), (True, False), (False, True), (False, False)]
    ):
        rows.append(
            {
                "label": label,
                "predicted_match": predicted,
                "latency_ms": index + 1,
                "reference_retrieved": predicted,
                "geometry_validated": predicted,
                "abstention": not predicted,
                "expected_abstention": None,
                "evidence_complete": index != 3,
                "policy_action": "REVIEW",
                "expected_policy": "REVIEW",
                "review_threshold_positive": predicted,
                "localization_success": None,
            }
        )
    metrics = summarize(rows)
    assert metrics["precision"] == metrics["recall"] == 0.5
    assert metrics["false_positive_rate"] == metrics["false_negative_rate"] == 0.5
    assert metrics["false_positive_burden_per_1000_negative_scans"] == 500
    assert metrics["median_latency_ms"] == 2.5
    assert metrics["p95_latency_ms"] == 4
    assert metrics["complete_evidence_packet_rate"] == 0.75
    assert metrics["policy_decision_accuracy"] == 1
    assert metrics["human_override_rate"] is None
    assert metrics["review_time_ms"] is None
    assert metrics["correctly_abstained_rate"] is None
    assert metrics["acceptable_false_positive_burden_established"] is False


def test_benchmark_calls_real_backend_keeps_network_off_and_seals_report(tmp_path, monkeypatch):
    def no_network(*_args, **_kwargs):
        raise AssertionError("The internal benchmark must not make network calls")

    monkeypatch.setattr(socket, "create_connection", no_network)
    manifest = generate_dataset(tmp_path / "dataset", source_count=1)
    payload = json.loads(manifest.read_text())
    # One actual exact-copy scan plus independent policy/coverage scenarios.
    payload["cases"] = [payload["cases"][0]] + [
        case for case in payload["cases"] if case["group"] == "POLICY_AND_COVERAGE"
    ]
    manifest.write_text(json.dumps(payload))
    report = run_benchmark(manifest)
    assert validate_benchmark_report_payload(report)["valid"] is True
    assert report["evaluation_grade"] == "SMOKE_TEST_ONLY"
    assert report["evaluation_eligible"] is False
    assert report["provider_availability"]["ai_origin"] is False
    assert report["provider_availability"]["ai_image_to_image"]["state"] == "UNAVAILABLE"
    assert report["metrics"]["policy_labeled_cases"] == 3
    assert report["metrics"]["policy_decision_accuracy"] == 1
    assert report["metrics"]["correctly_abstained_rate"] == 1
    assert report["metrics"]["human_override_rate"] is None
    assert report["records"][0]["predicted_match"] is True
    assert report["records"][0]["evidence_packet_hash"]
    assert (manifest.parent / "report.json").is_file()


def test_runner_rejects_changed_fixture_bytes_before_scanning(tmp_path):
    manifest = generate_dataset(tmp_path / "dataset", source_count=1)
    payload = json.loads(manifest.read_text())
    (manifest.parent / payload["references"][0]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="Fixture hash mismatch"):
        run_benchmark(manifest, max_cases=1)
