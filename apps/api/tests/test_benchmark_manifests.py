import json
from pathlib import Path

import pytest

from app.services.benchmark_manifest import (
    benchmark_run_identity,
    bind_benchmark_input_to_corpus,
    load_corpus_manifest,
    validate_manifest_set,
)
from app.services.model_bundle import load_model_bundle


def _item(
    asset_id: str,
    digest_character: str,
    lineage: str,
    *,
    exposure: str = "NEVER_SEEN",
    **overrides,
) -> dict:
    payload = {
        "asset_id": asset_id,
        "location": f"external-authorized/{asset_id}.png",
        "sha256": digest_character * 64,
        "source_lineage_id": lineage,
        "rights": {"state": "AUTHORIZED", "reference": f"permission:{asset_id}"},
        "exposure_state": exposure,
        "label": {"match": False},
        "cohorts": ["HARD_NEGATIVE"],
    }
    payload.update(overrides)
    return payload


def _manifest(partition: str, items: list[dict], *, lane: str = "COPY") -> dict:
    return {
        "schema": "creatorproof.corpus_manifest.v1",
        "manifest_id": f"test-{lane.lower()}-{partition.lower()}-v1",
        "dataset_id": "test-dataset-v1",
        "lane": lane,
        "partition": partition,
        "domain_id": "TEST_CREATIVE_OPERATIONS",
        "items": items,
        "limitations": ["Test fixture only."],
    }


def _write(tmp_path, name: str, payload: dict):
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_valid_manifest_set_has_stable_identity(tmp_path):
    calibration = load_corpus_manifest(
        _write(tmp_path, "calibration.json", _manifest("CALIBRATION", [_item("a", "a", "l1")]))
    )
    test = load_corpus_manifest(
        _write(tmp_path, "test.json", _manifest("TEST", [_item("b", "b", "l2")]))
    )

    report = validate_manifest_set([calibration, test])

    assert report["valid"] is True
    assert report["item_count"] == 2
    assert len(report["manifest_set_digest_sha256"]) == 64


def test_source_lineage_cannot_leak_across_partitions(tmp_path):
    calibration = load_corpus_manifest(
        _write(tmp_path, "calibration.json", _manifest("CALIBRATION", [_item("a", "a", "l1")]))
    )
    test = load_corpus_manifest(
        _write(tmp_path, "test.json", _manifest("TEST", [_item("b", "b", "l1")]))
    )

    with pytest.raises(ValueError, match="source lineage leaks"):
        validate_manifest_set([calibration, test])


def test_test_partition_rejects_demo_exposure(tmp_path):
    path = _write(
        tmp_path,
        "test.json",
        _manifest("TEST", [_item("a", "a", "l1", exposure="DEMO_EXPOSED")]),
    )

    with pytest.raises(ValueError, match="NEVER_SEEN"):
        load_corpus_manifest(path)


def test_manifest_requires_authorized_rights_record(tmp_path):
    item = _item("a", "a", "l1")
    item["rights"] = {"state": "UNKNOWN", "reference": "none"}
    path = _write(tmp_path, "test.json", _manifest("TEST", [item]))

    with pytest.raises(ValueError, match="not authorized"):
        load_corpus_manifest(path)


def test_creator_profile_anchor_requires_confirmed_consent(tmp_path):
    item = _item("a", "a", "l1", profile_id="profile-a", profile_consent_state="NOT_CONFIRMED")
    path = _write(
        tmp_path,
        "style.json",
        _manifest("DEMO", [item], lane="CREATOR_PROFILE"),
    )

    with pytest.raises(ValueError, match="CONFIRMED consent"):
        load_corpus_manifest(path)


def test_benchmark_identity_binds_manifest_and_model_bundle():
    payload = _manifest("DEMO", [_item("a", "a", "l1", exposure="DEMO_EXPOSED")])
    bundle = load_model_bundle(
        Path("model_lab/bundles/creatorproof-runtime-ready-v1.json"),
        strict=True,
    )

    identity = benchmark_run_identity(
        lane="COPY",
        manifest_payload=payload,
        model_bundle=bundle,
        threshold_policy_id="copy-prototype-v1",
    )

    assert len(identity["manifest_digest_sha256"]) == 64
    assert identity["model_bundle_id"] == bundle.bundle_id
    assert identity["model_bundle_manifest_digest_sha256"] == bundle.manifest_digest_sha256
    assert len(identity["run_identity_digest_sha256"]) == 64


def test_benchmark_input_can_bind_every_asset_to_held_out_manifest(tmp_path):
    corpus_path = _write(
        tmp_path,
        "corpus-test.json",
        _manifest("TEST", [_item("a", "a", "l1")]),
    )
    benchmark_path = _write(
        tmp_path,
        "benchmark.json",
        {"corpus_manifest_paths": [corpus_path.name]},
    )

    result = bind_benchmark_input_to_corpus(
        benchmark_manifest_path=benchmark_path,
        benchmark_payload=json.loads(benchmark_path.read_text(encoding="utf-8")),
        lane="COPY",
        referenced_locations=["external-authorized/a.png"],
    )

    assert result["state"] == "VALID_TEST_CORPUS_BINDING"
    assert result["evaluation_eligible"] is True
    assert result["promotion_eligible"] is False
    assert len(result["manifest_set_digest_sha256"]) == 64
    assert result["asset_bindings"] == [
        {
            "location": "external-authorized/a.png",
            "asset_id": "a",
            "source_lineage_id": "l1",
            "partition": "TEST",
            "cohorts": ["HARD_NEGATIVE"],
        }
    ]


def test_legacy_benchmark_manifest_is_forced_to_smoke_only(tmp_path):
    result = bind_benchmark_input_to_corpus(
        benchmark_manifest_path=tmp_path / "benchmark.json",
        benchmark_payload={"cases": []},
        lane="COPY",
        referenced_locations=[],
    )

    assert result == {
        "state": "LEGACY_UNVALIDATED_MANIFEST",
        "evaluation_eligible": False,
        "promotion_eligible": False,
        "reason_codes": ["CORPUS_MANIFEST_BINDING_NOT_DECLARED"],
        "manifest_set_digest_sha256": None,
    }


def test_benchmark_binding_rejects_unregistered_asset_location(tmp_path):
    corpus_path = _write(
        tmp_path,
        "corpus-test.json",
        _manifest("TEST", [_item("a", "a", "l1")]),
    )
    payload = {"corpus_manifest_paths": [corpus_path.name]}

    with pytest.raises(ValueError, match="missing from corpus"):
        bind_benchmark_input_to_corpus(
            benchmark_manifest_path=tmp_path / "benchmark.json",
            benchmark_payload=payload,
            lane="COPY",
            referenced_locations=["external-authorized/not-registered.png"],
        )
