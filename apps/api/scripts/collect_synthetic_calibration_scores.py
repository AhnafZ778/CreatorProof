from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from app.core.config import Settings
from app.domain.enums import ProvenanceStatus
from app.providers.contracts import ProvenanceEvidence
from app.providers.synthetic_detection import SyntheticDetectorRouter
from app.services.benchmark_manifest import (
    benchmark_run_identity,
    bind_benchmark_input_to_corpus,
)
from app.services.model_bundle import canonical_json_digest, load_model_bundle
from app.services.synthetic_analysis import analyze_synthetic_origin


def _load_image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        image.load()
    return image


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Collect provider/model-version raw aggregate scores from an authorized calibration "
            "manifest. The output is suitable for scripts.calibrate_synthetic_scores."
        )
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    items = manifest.get("images")
    if not isinstance(items, list) or not items:
        raise SystemExit("Manifest must contain a non-empty images array.")
    if manifest.get("partition") not in {None, "calibration"}:
        raise SystemExit("This collector accepts only a calibration partition manifest.")
    corpus_integrity = bind_benchmark_input_to_corpus(
        benchmark_manifest_path=args.manifest,
        benchmark_payload=manifest,
        lane="AI_ORIGIN",
        referenced_locations=[str(item["path"]) for item in items],
        required_partition="CALIBRATION",
    )

    settings = Settings()
    bundle = load_model_bundle(
        settings.model_bundle_path,
        strict=settings.model_bundle_strict,
    )
    router = SyntheticDetectorRouter(
        mode=settings.synthetic_detector,
        community_model_path=settings.synthetic_community_model_path,
        torchscript_model_path=settings.synthetic_torchscript_model_path,
        device=settings.synthetic_device,
        external_detectors_json=settings.synthetic_external_detectors_json,
        evidence_family_registry_path=settings.synthetic_evidence_family_registry_path,
        calibration_path=Path("__calibration_disabled_during_collection__.json"),
        min_calibration_samples=settings.synthetic_min_calibration_samples,
        min_calibration_class_samples=settings.synthetic_min_calibration_class_samples,
        community_expected_sha256=(
            settings.synthetic_community_expected_sha256
            or bundle.declared_artifact_sha256("origin-community-forensics")
        ),
        calibration_domain_id=settings.synthetic_calibration_domain_id,
        crop_policy_id=settings.synthetic_crop_policy_id,
        model_bundle_manifest_digest=bundle.manifest_digest_sha256 or "",
        sightengine_api_user=settings.sightengine_api_user,
        sightengine_api_secret=settings.sightengine_api_secret,
        sightengine_timeout_seconds=settings.sightengine_timeout_seconds,
    )
    if not router.available:
        raise SystemExit(json.dumps(router.status(), indent=2))

    provenance = ProvenanceEvidence(
        status=ProvenanceStatus.NOT_PRESENT,
        provider="calibration-collector-no-manifest",
        reason_codes=["PROVENANCE_EXCLUDED_FROM_MODEL_SCORE_CALIBRATION"],
    )
    rows: list[dict] = []
    manifest_root = args.manifest.parent.resolve()
    for item in items:
        label = int(item["label"])
        if label not in {0, 1}:
            raise SystemExit("Image labels must be 0 for human-source or 1 for AI-generated.")
        relative_path = str(item["path"])
        image_path = (manifest_root / relative_path).resolve()
        result = analyze_synthetic_origin(
            image=_load_image(image_path),
            detector_router=router,
            provenance=provenance,
            settings=settings,
            source_media=image_path.read_bytes(),
            source_filename=image_path.name,
        )
        for member in result.get("members") or []:
            rows.append(
                {
                    "partition": "calibration",
                    "path": relative_path,
                    "label": label,
                    "provider": member["provider"],
                    "model_version": member.get("model_version"),
                    "artifact_sha256": member.get("artifact_sha256"),
                    "preprocessing_identity": member.get("preprocessing_identity"),
                    "evidence_family": member.get("evidence_family"),
                    "score": member["aggregate_score"],
                    "generator": item.get("generator"),
                    "source": item.get("source"),
                    "lineage_id": item.get("lineage_id"),
                }
            )

    output = {
        "schema": "creatorproof.synthetic_score_manifest.v2",
        "run_identity": benchmark_run_identity(
            lane="AI_ORIGIN",
            manifest_payload=manifest,
            model_bundle=bundle,
            threshold_policy_id="creatorproof-origin-calibration-collection-v2",
            corpus_manifest_set_digest_sha256=corpus_integrity["manifest_set_digest_sha256"],
        ),
        "score_rows_digest_sha256": canonical_json_digest(rows),
        "corpus_integrity": corpus_integrity,
        "corpus_manifest_set_digest_sha256": corpus_integrity["manifest_set_digest_sha256"],
        "model_bundle_manifest_digest_sha256": bundle.manifest_digest_sha256,
        "dataset_id": manifest.get("dataset_id"),
        "domain_id": manifest.get("domain_id") or manifest.get("domain"),
        "crop_policy_id": settings.synthetic_crop_policy_id,
        "partition": "calibration",
        "created_at": datetime.now(UTC).isoformat(),
        "provider_status": router.status(),
        "rows": rows,
        "limitations": [
            "This file fits calibration only and must not be reused as the locked final test set.",
            "Changing model weights, preprocessing, or target domain invalidates the fit.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "rows": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
