from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from app.services.model_bundle import canonical_json_digest


def _logit(value: float) -> float:
    clipped = min(max(float(value), 1e-6), 1.0 - 1e-6)
    return math.log(clipped / (1.0 - clipped))


def _sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -50.0, 50.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _fit(scores: list[float], labels: list[int], regularization: float) -> tuple[float, float]:
    features = np.column_stack(
        [np.asarray([_logit(score) for score in scores]), np.ones(len(scores))]
    )
    target = np.asarray(labels, dtype=np.float64)
    weights = np.asarray([1.0, 0.0], dtype=np.float64)
    penalty = np.diag([regularization, regularization * 0.1])
    for _ in range(100):
        predictions = _sigmoid(features @ weights)
        variance = np.clip(predictions * (1.0 - predictions), 1e-6, None)
        gradient = features.T @ (predictions - target) + penalty @ weights
        hessian = features.T @ (features * variance[:, None]) + penalty
        step = np.linalg.solve(hessian, gradient)
        weights -= step
        if float(np.linalg.norm(step)) < 1e-8:
            break
    if weights[0] <= 0 or not np.isfinite(weights).all():
        raise ValueError("Calibration fit inverted the detector or was non-finite")
    return float(weights[0]), float(weights[1])


def _ece(labels: np.ndarray, probabilities: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    result = 0.0
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        selected = (probabilities >= lower) & (
            probabilities <= upper if index == bins - 1 else probabilities < upper
        )
        count = int(selected.sum())
        if count:
            result += (
                count
                / len(labels)
                * abs(float(probabilities[selected].mean()) - float(labels[selected].mean()))
            )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fit provider-specific Platt calibration on a held-out score manifest."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-per-class", type=int, default=25)
    parser.add_argument("--regularization", type=float, default=1e-3)
    args = parser.parse_args()

    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise SystemExit("Manifest must contain a rows array.")
    corpus_integrity = payload.get("corpus_integrity") or {}
    if corpus_integrity.get("state") != "VALID_CALIBRATION_CORPUS_BINDING":
        raise SystemExit(
            "Calibration requires a validated CALIBRATION corpus binding; "
            "legacy score manifests cannot produce a promoted fit."
        )
    required_context = (
        "dataset_id",
        "domain_id",
        "crop_policy_id",
        "corpus_manifest_set_digest_sha256",
        "model_bundle_manifest_digest_sha256",
    )
    missing_context = [field for field in required_context if not payload.get(field)]
    if missing_context:
        raise SystemExit("Calibration context is incomplete: " + ",".join(missing_context))
    actual_rows_digest = canonical_json_digest(rows)
    if (
        payload.get("score_rows_digest_sha256")
        and payload["score_rows_digest_sha256"] != actual_rows_digest
    ):
        raise SystemExit("Calibration score rows digest does not match the manifest.")
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict) or row.get("partition", "calibration") != "calibration":
            continue
        score = float(row["score"])
        label = int(row["label"])
        if not 0.0 <= score <= 1.0 or label not in {0, 1}:
            raise SystemExit("Every score must be in [0,1] and every label must be 0 or 1.")
        grouped[str(row["provider"])].append(row)

    providers: dict[str, dict] = {}
    for provider, provider_rows in sorted(grouped.items()):
        labels = [int(row["label"]) for row in provider_rows]
        positives = sum(labels)
        negatives = len(labels) - positives
        if min(positives, negatives) < args.minimum_per_class:
            continue
        scores = [float(row["score"]) for row in provider_rows]
        slope, intercept = _fit(scores, labels, args.regularization)
        calibrated = _sigmoid(slope * np.asarray([_logit(score) for score in scores]) + intercept)
        label_array = np.asarray(labels, dtype=np.float64)
        versions = sorted(
            {str(row["model_version"]) for row in provider_rows if row.get("model_version")}
        )
        artifacts = sorted(
            {str(row["artifact_sha256"]) for row in provider_rows if row.get("artifact_sha256")}
        )
        preprocessing = sorted(
            {
                str(row["preprocessing_identity"])
                for row in provider_rows
                if row.get("preprocessing_identity")
            }
        )
        if len(versions) != 1:
            raise SystemExit(f"Provider {provider} must have exactly one model_version.")
        if len(artifacts) != 1:
            raise SystemExit(f"Provider {provider} must have exactly one artifact_sha256.")
        if len(preprocessing) != 1:
            raise SystemExit(f"Provider {provider} must have exactly one preprocessing_identity.")
        providers[provider] = {
            "slope": slope,
            "intercept": intercept,
            "model_version": versions[0],
            "artifact_sha256": artifacts[0],
            "preprocessing_identity": preprocessing[0],
            "sample_count": len(labels),
            "positive_count": positives,
            "negative_count": negatives,
            "dataset_id": payload.get("dataset_id"),
            "domain_id": payload.get("domain_id") or payload.get("domain"),
            "crop_policy_id": payload.get("crop_policy_id"),
            "corpus_manifest_set_digest_sha256": payload.get("corpus_manifest_set_digest_sha256"),
            "model_bundle_manifest_digest_sha256": payload.get(
                "model_bundle_manifest_digest_sha256"
            ),
            "brier_score": float(np.mean((calibrated - label_array) ** 2)),
            "expected_calibration_error": _ece(label_array, calibrated),
            "fit_method": "L2_REGULARIZED_PLATT_SCALING_ON_RAW_SCORE_LOGITS",
        }
    if not providers:
        raise SystemExit("No provider had enough positive and negative calibration samples.")

    output = {
        "schema": "creatorproof.synthetic_calibration.v2",
        "created_at": datetime.now(UTC).isoformat(),
        "source_manifest": str(args.manifest),
        "source_run_identity": payload.get("run_identity"),
        "source_corpus_integrity": corpus_integrity,
        "source_score_rows_digest_sha256": (
            payload.get("score_rows_digest_sha256") or actual_rows_digest
        ),
        "calibration_parameters_digest_sha256": canonical_json_digest(providers),
        "providers": providers,
        "limitations": [
            "Calibration applies only to the recorded domain and model version.",
            "The calibration set must never be reused as the final evaluation set.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
