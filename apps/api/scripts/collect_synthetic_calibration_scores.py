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

    settings = Settings()
    router = SyntheticDetectorRouter(
        mode=settings.synthetic_detector,
        community_model_path=settings.synthetic_community_model_path,
        torchscript_model_path=settings.synthetic_torchscript_model_path,
        device=settings.synthetic_device,
        external_detectors_json=settings.synthetic_external_detectors_json,
        calibration_path=Path("__calibration_disabled_during_collection__.json"),
        min_calibration_samples=settings.synthetic_min_calibration_samples,
        min_calibration_class_samples=settings.synthetic_min_calibration_class_samples,
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
        result = analyze_synthetic_origin(
            image=_load_image((manifest_root / relative_path).resolve()),
            detector_router=router,
            provenance=provenance,
            settings=settings,
        )
        for member in result.get("members") or []:
            rows.append(
                {
                    "partition": "calibration",
                    "path": relative_path,
                    "label": label,
                    "provider": member["provider"],
                    "model_version": member.get("model_version"),
                    "evidence_family": member.get("evidence_family"),
                    "score": member["aggregate_score"],
                    "generator": item.get("generator"),
                    "source": item.get("source"),
                    "lineage_id": item.get("lineage_id"),
                }
            )

    output = {
        "schema": "creatorproof.synthetic_score_manifest.v1",
        "dataset_id": manifest.get("dataset_id"),
        "domain": manifest.get("domain"),
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
