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
from app.services.benchmark_manifest import (
    benchmark_run_identity,
    bind_benchmark_input_to_corpus,
    corpus_asset_binding,
    seal_benchmark_report,
)
from app.services.benchmark_statistics import binary_rate, lineage_cluster_bootstrap_interval
from app.services.model_bundle import load_model_bundle
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
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    args = parser.parse_args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    items = payload.get("images")
    if not isinstance(items, list) or not items:
        raise SystemExit("Manifest must contain a non-empty images array.")
    corpus_integrity = bind_benchmark_input_to_corpus(
        benchmark_manifest_path=args.manifest,
        benchmark_payload=payload,
        lane="AI_ORIGIN",
        referenced_locations=[str(item["path"]) for item in items],
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
        calibration_path=settings.synthetic_calibration_path,
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
        provider="benchmark-no-manifest",
        reason_codes=["BENCHMARK_DOES_NOT_USE_PROVENANCE"],
    )
    rows: list[dict] = []
    groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        label = int(item["label"])
        if label not in {0, 1}:
            raise SystemExit("Image labels must be 0 for real or 1 for AI-generated.")
        image_path = (args.manifest.parent / str(item["path"])).resolve()
        result = analyze_synthetic_origin(
            image=_image(image_path),
            detector_router=router,
            provenance=provenance,
            settings=settings,
            source_media=image_path.read_bytes(),
            source_filename=image_path.name,
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
        correct = prediction == bool(label)
        groups[group].append({"correct": correct, "abstained": abstained, "label": label})
        binding = corpus_asset_binding(corpus_integrity, str(item["path"]))
        rows.append(
            {
                "path": item["path"],
                "asset_id": binding["asset_id"],
                "source_lineage_id": binding["source_lineage_id"],
                "cohorts": binding["cohorts"],
                "label": label,
                "group": group,
                "score": score,
                "classification": classification,
                "prediction": int(prediction),
                "correct": correct,
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
    calibration_gate_passed = bool(
        scored
        and all(row["all_members_calibrated"] for row in scored)
        and all(
            int(row.get("evidence_family_count") or 0)
            >= settings.synthetic_min_independent_families
            for row in scored
        )
    )
    intervals = {
        "roc_auc": lineage_cluster_bootstrap_interval(
            scored,
            lambda sample: _auc(
                [int(row["label"]) for row in sample],
                [float(row["score"]) for row in sample],
            ),
            iterations=args.bootstrap_iterations,
            minimum_clusters=20,
        ),
        "average_precision": lineage_cluster_bootstrap_interval(
            scored,
            lambda sample: _average_precision(
                [int(row["label"]) for row in sample],
                [float(row["score"]) for row in sample],
            ),
            iterations=args.bootstrap_iterations,
            minimum_clusters=20,
        ),
        "decided_false_positive_rate": lineage_cluster_bootstrap_interval(
            decided,
            lambda sample: binary_rate(
                sample,
                numerator=lambda row: bool(row["prediction"]),
                denominator=lambda row: not bool(row["label"]),
            ),
            iterations=args.bootstrap_iterations,
            minimum_clusters=20,
        ),
        "decided_recall": lineage_cluster_bootstrap_interval(
            decided,
            lambda sample: binary_rate(
                sample,
                numerator=lambda row: bool(row["prediction"]),
                denominator=lambda row: bool(row["label"]),
            ),
            iterations=args.bootstrap_iterations,
            minimum_clusters=20,
        ),
        "selective_accuracy": lineage_cluster_bootstrap_interval(
            decided,
            lambda sample: binary_rate(sample, numerator=lambda row: row["correct"]),
            iterations=args.bootstrap_iterations,
            minimum_clusters=20,
        ),
    }
    uncertainty_gate_passed = all(
        interval["eligible_for_acceptance"] for interval in intervals.values()
    )
    evaluation_eligible = bool(
        positive_count >= 100
        and negative_count >= 100
        and len(fake_generators) >= 5
        and len(real_sources) >= 3
        and payload.get("generator_disjoint") is True
        and uncertainty_gate_passed
        and corpus_integrity["evaluation_eligible"]
    )
    error_gallery = [
        {
            "path": row["path"],
            "asset_id": row["asset_id"],
            "source_lineage_id": row["source_lineage_id"],
            "cohorts": row["cohorts"],
            "group": row["group"],
            "error_type": (
                "ABSTENTION"
                if row["abstained"]
                else "FALSE_POSITIVE"
                if row["prediction"] and not row["label"]
                else "FALSE_NEGATIVE"
            ),
            "classification": row["classification"],
            "score": row["score"],
        }
        for row in rows
        if row["abstained"] or not row["correct"]
    ]
    output = {
        "schema": "creatorproof.synthetic_benchmark.v2",
        "run_identity": benchmark_run_identity(
            lane="AI_ORIGIN",
            manifest_payload=payload,
            model_bundle=bundle,
            threshold_policy_id="creatorproof-origin-evidence-operating-points-v3",
            corpus_manifest_set_digest_sha256=corpus_integrity["manifest_set_digest_sha256"],
        ),
        "corpus_integrity": corpus_integrity,
        "detectors": router.status(),
        "dataset_id": payload.get("dataset_id"),
        "evaluation_grade": (
            "GENERATOR_DISJOINT_EVALUATION" if evaluation_eligible else "SMOKE_TEST_ONLY"
        ),
        "evaluation_eligible": evaluation_eligible,
        "promotion_eligible": False,
        "promotion_decision": {
            "state": "NOT_EVALUATED",
            "reason_code": "ACCEPTANCE_POLICY_NOT_APPLIED",
            "acceptance_policy_digest_sha256": None,
        },
        "minimum_support_gate": {
            "ai_images": 100,
            "real_images": 100,
            "fake_generators": 5,
            "real_sources": 3,
            "generator_disjoint": True,
            "source_lineage_clusters": 20,
        },
        "operating_configuration": {
            "origin_policy_id": "creatorproof-origin-evidence-operating-points-v3",
            "likely_threshold": settings.synthetic_likely_threshold,
            "review_threshold": settings.synthetic_review_threshold,
            "minimum_independent_families": settings.synthetic_min_independent_families,
            "crop_policy_id": settings.synthetic_crop_policy_id,
            "bootstrap_iterations": args.bootstrap_iterations,
        },
        "scored_images": len(scored),
        "ai_images": positive_count,
        "real_images": negative_count,
        "calibration_gate_passed": calibration_gate_passed,
        "roc_auc": _auc(labels, scores),
        "average_precision": _average_precision(labels, scores),
        **_operating_points(labels, scores),
        "abstention_rate": sum(row["abstained"] for row in rows) / len(rows),
        "selective_coverage": len(decided) / len(rows),
        "selective_accuracy": decided_correct / len(decided) if decided else None,
        "selective_accuracy_wilson_95": _wilson(decided_correct, len(decided)),
        "lineage_clustered_confidence_intervals": intervals,
        "uncertainty_gate_passed": uncertainty_gate_passed,
        "calibration_diagnostics": {
            "state": "NOT_APPLICABLE_TO_ENSEMBLE_SIGNAL_SCORE",
            "brier_score": None,
            "expected_calibration_error": None,
            "reason_code": "FUSED_DETECTOR_SCORE_IS_NOT_A_PROBABILITY",
        },
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
        "error_gallery": error_gallery,
        "rows": rows,
        "warning": (
            "This run cannot support deployment claims. Valid TEST corpus binding, "
            "generator-disjoint data, transforms, calibration, and intervals are required."
            if not evaluation_eligible
            else "Passing the sample gate does not establish universal AI-origin detection."
        ),
    }
    output = seal_benchmark_report(output)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
