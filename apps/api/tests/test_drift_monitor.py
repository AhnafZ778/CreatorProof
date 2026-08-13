import json

from app.services.drift_monitor import (
    DriftBaselineRegistry,
    aggregate_packet_telemetry,
    evaluate_runtime_drift,
    load_drift_baseline_registry,
)


def _packet(mean: float, *, digest: str = "b" * 64) -> dict:
    return {
        "runtime_telemetry": {
            "schema": "creatorproof.runtime_telemetry.v1",
            "metadata": {
                "model_bundle_id": "bundle-v1",
                "model_bundle_manifest_digest_sha256": digest,
            },
            "score_summaries": {
                "copy_evidence_index": {
                    "count": 10,
                    "mean": mean,
                    "minimum": mean,
                    "maximum": mean,
                }
            },
        }
    }


def test_checked_in_empty_registry_is_explicitly_not_configured():
    registry = load_drift_baseline_registry("model_lab/registries/drift-baselines.v1.json")

    result = evaluate_runtime_drift(aggregate_packet_telemetry([_packet(0.5)]), registry)

    assert result["state"] == "NOT_CONFIGURED"
    assert result["revalidation_required"] is False


def test_material_score_shift_triggers_revalidation():
    payload = {
        "schema": "creatorproof.drift_baseline_registry.v1",
        "registry_id": "test-registry",
        "records": [
            {
                "lane": "COPY",
                "score_name": "copy_evidence_index",
                "domain_id": "TEST",
                "model_bundle_id": "bundle-v1",
                "model_bundle_manifest_digest_sha256": "b" * 64,
                "source_report_digest_sha256": "c" * 64,
                "baseline_mean": 0.30,
                "baseline_standard_deviation": 0.05,
                "minimum_current_observations": 20,
                "warning_standardized_shift": 2.0,
                "revalidation_standardized_shift": 3.0,
            }
        ],
    }
    registry = DriftBaselineRegistry(
        registry_id="test-registry",
        records=tuple(payload["records"]),
        digest_sha256="d" * 64,
    )
    aggregate = aggregate_packet_telemetry([_packet(0.60), _packet(0.60)])

    result = evaluate_runtime_drift(aggregate, registry)

    assert result["state"] == "REVALIDATION_REQUIRED"
    assert result["revalidation_required"] is True
    assert result["checks"][0]["standardized_mean_shift"] == 6.0


def test_registry_loader_rejects_duplicate_lane_score_records(tmp_path):
    record = {
        "lane": "COPY",
        "score_name": "copy_evidence_index",
        "domain_id": "TEST",
        "model_bundle_id": "bundle-v1",
        "model_bundle_manifest_digest_sha256": "b" * 64,
        "source_report_digest_sha256": "c" * 64,
        "baseline_mean": 0.3,
        "baseline_standard_deviation": 0.05,
        "minimum_current_observations": 20,
        "warning_standardized_shift": 2.0,
        "revalidation_standardized_shift": 3.0,
    }
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "schema": "creatorproof.drift_baseline_registry.v1",
                "registry_id": "duplicate",
                "records": [record, record],
            }
        ),
        encoding="utf-8",
    )

    try:
        load_drift_baseline_registry(path)
    except ValueError as exc:
        assert "unique" in str(exc)
    else:
        raise AssertionError("duplicate records were accepted")
