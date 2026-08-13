from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.config import Settings
from app.domain.enums import ProvenanceStatus
from app.providers.contracts import ProvenanceEvidence
from app.providers.synthetic_detection import SyntheticDetectorRouter
from app.services.synthetic_analysis import analyze_synthetic_origin


def _image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        result = opened.convert("RGB")
        result.load()
    return result


def _auc(labels: list[int], scores: list[float]) -> float | None:
    positives = [score for label, score in zip(labels, scores, strict=True) if label == 1]
    negatives = [score for label, score in zip(labels, scores, strict=True) if label == 0]
    if not positives or not negatives:
        return None
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives
        for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def _average_precision(labels: list[int], scores: list[float]) -> float | None:
    positive_count = sum(labels)
    if positive_count == 0:
        return None
    ranked = sorted(zip(scores, labels, strict=True), key=lambda item: item[0], reverse=True)
    true_positives = 0
    precision_sum = 0.0
    for rank, (_, label) in enumerate(ranked, start=1):
        if label:
            true_positives += 1
            precision_sum += true_positives / rank
    return precision_sum / positive_count


def _wilson(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    estimate = successes / total
    denominator = 1.0 + z**2 / total
    center = (estimate + z**2 / (2.0 * total)) / denominator
    half_width = (
        z * math.sqrt(estimate * (1.0 - estimate) / total + z**2 / (4.0 * total**2)) / denominator
    )
    return [max(0.0, center - half_width), min(1.0, center + half_width)]


def _operating_points(labels: list[int], scores: list[float]) -> dict:
    positives = np.asarray([score for label, score in zip(labels, scores, strict=True) if label])
    negatives = np.asarray(
        [score for label, score in zip(labels, scores, strict=True) if not label]
    )
    if not len(positives) or not len(negatives):
        return {"fpr_at_95_tpr": None, "tpr_at_1_fpr": None}
    threshold_95_tpr = float(np.quantile(positives, 0.05, method="lower"))
    threshold_1_fpr = float(np.quantile(negatives, 0.99, method="higher"))
    return {
        "fpr_at_95_tpr": float(np.mean(negatives >= threshold_95_tpr)),
        "fpr_at_95_tpr_threshold": threshold_95_tpr,
        "tpr_at_1_fpr": float(np.mean(positives >= threshold_1_fpr)),
        "tpr_at_1_fpr_threshold": threshold_1_fpr,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark AI-origin detection on a labeled, held-out image manifest."
    )
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    items = payload.get("images")
    if not isinstance(items, list) or not items:
        raise SystemExit("Manifest must contain a non-empty images array.")

    settings = Settings()
    router = SyntheticDetectorRouter(
        mode=settings.synthetic_detector,
        community_model_path=settings.synthetic_community_model_path,
        torchscript_model_path=settings.synthetic_torchscript_model_path,
        device=settings.synthetic_device,
        external_detectors_json=settings.synthetic_external_detectors_json,
        calibration_path=settings.synthetic_calibration_path,
        min_calibration_samples=settings.synthetic_min_calibration_samples,
        min_calibration_class_samples=settings.synthetic_min_calibration_class_samples,
    )
    if not router.available:
        raise SystemExit(json.dumps(router.status(), indent=2))

    provenance = ProvenanceEvidence(
        status=ProvenanceStatus.NOT_PRESENT,
        provider="benchmark-no-manifest",
        reason_codes=["BENCHMARK_DOES_NOT_USE_PROVENANCE"],
    )
    rows: list[dict] = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        label = int(item["label"])
        if label not in {0, 1}:
            raise SystemExit("Image labels must be 0 for real or 1 for AI-generated.")
        result = analyze_synthetic_origin(
            image=_image((args.manifest.parent / str(item["path"])).resolve()),
            detector_router=router,
            provenance=provenance,
            settings=settings,
        )
        score = result.get("fused_detector_score")
        group = str(item.get("generator") or item.get("source") or "unknown")
        classification = str(result["classification"])
        abstained = (
            classification.startswith("INCONCLUSIVE")
            or classification.startswith("AI_ORIGIN_INCONCLUSIVE")
            or classification
            in {
                "AI_ORIGIN_REVIEW_CANDIDATE",
                "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE",
            }
        )
        prediction = classification in {"LIKELY_AI_GENERATED", "AI_PROVENANCE_CONFIRMED"}
        groups[group].append(
            {"correct": prediction == bool(label), "abstained": abstained, "label": label}
        )
        rows.append(
            {
                "path": item["path"],
                "label": label,
                "group": group,
                "score": score,
                "classification": classification,
                "prediction": int(prediction),
                "abstained": abstained,
                "transform_stability": result.get("transform_stability"),
                "all_members_calibrated": bool(result.get("members"))
                and all(member.get("calibrated") for member in result["members"]),
                "evidence_family_count": result.get("evidence_family_count"),
                "negative_clearance_supported": result.get("negative_clearance_supported"),
            }
        )

    scored = [row for row in rows if row["score"] is not None]
    labels = [int(row["label"]) for row in scored]
    scores = [float(row["score"]) for row in scored]
    positive_count = sum(labels)
    negative_count = len(labels) - positive_count
    fake_generators = {row["group"] for row in scored if row["label"] == 1}
    real_sources = {row["group"] for row in scored if row["label"] == 0}
    decided = [row for row in rows if not row["abstained"]]
    decided_correct = sum(int(row["prediction"] == row["label"]) for row in decided)
    true_positive = sum(int(row["prediction"] == 1 and row["label"] == 1) for row in decided)
    false_positive = sum(int(row["prediction"] == 1 and row["label"] == 0) for row in decided)
    true_negative = sum(int(row["prediction"] == 0 and row["label"] == 0) for row in decided)
    false_negative = sum(int(row["prediction"] == 0 and row["label"] == 1) for row in decided)
    recall_denominator = true_positive + false_negative
    specificity_denominator = true_negative + false_positive
    precision_denominator = true_positive + false_positive
    promotion_eligible = bool(
        positive_count >= 100
        and negative_count >= 100
        and len(fake_generators) >= 5
        and len(real_sources) >= 3
        and payload.get("generator_disjoint") is True
    )
    output = {
        "schema": "creatorproof.synthetic_benchmark.v1",
        "detectors": router.status(),
        "dataset_id": payload.get("dataset_id"),
        "evaluation_grade": (
            "GENERATOR_DISJOINT_EVALUATION" if promotion_eligible else "SMOKE_TEST_ONLY"
        ),
        "promotion_eligible": promotion_eligible,
        "minimum_support_gate": {
            "ai_images": 100,
            "real_images": 100,
            "fake_generators": 5,
            "real_sources": 3,
            "generator_disjoint": True,
        },
        "scored_images": len(scored),
        "ai_images": positive_count,
        "real_images": negative_count,
        "roc_auc": _auc(labels, scores),
        "average_precision": _average_precision(labels, scores),
        **_operating_points(labels, scores),
        "abstention_rate": sum(row["abstained"] for row in rows) / len(rows),
        "selective_coverage": len(decided) / len(rows),
        "selective_accuracy": decided_correct / len(decided) if decided else None,
        "selective_accuracy_wilson_95": _wilson(decided_correct, len(decided)),
        "decision_confusion": {
            "true_positive": true_positive,
            "false_positive": false_positive,
            "true_negative": true_negative,
            "false_negative": false_negative,
            "precision": (true_positive / precision_denominator if precision_denominator else None),
            "recall": true_positive / recall_denominator if recall_denominator else None,
            "specificity": (
                true_negative / specificity_denominator if specificity_denominator else None
            ),
        },
        "group_accuracy": {
            group: {
                "images": len(values),
                "coverage": sum(not item["abstained"] for item in values) / len(values),
                "selective_accuracy": (
                    sum(item["correct"] for item in values if not item["abstained"])
                    / sum(not item["abstained"] for item in values)
                    if any(not item["abstained"] for item in values)
                    else None
                ),
            }
            for group, values in sorted(groups.items())
        },
        "rows": rows,
        "warning": (
            "This run cannot support deployment claims. Generator-disjoint data, social-media "
            "transforms, per-domain calibration, and confidence intervals are required."
            if not promotion_eligible
            else "Passing the sample gate does not establish universal AI-origin detection."
        ),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
