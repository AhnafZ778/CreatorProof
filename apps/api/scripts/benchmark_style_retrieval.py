from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.config import Settings
from app.providers.style_retrieval import StyleEmbeddingRouter
from app.services.style_readout import (
    aggregated_discrimination_gaps,
    corpus_profile_readout,
    normalize,
)


def _image(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        image.load()
    return image


def _roc_auc(labels: list[int], scores: list[float]) -> float | None:
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


def _equal_error_operating_point(
    labels: list[int], scores: list[float]
) -> tuple[float, float] | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    thresholds = sorted(set(scores), reverse=True)
    best: tuple[float, float, float] | None = None
    for threshold in thresholds:
        false_negative_rate = (
            sum(
                label == 1 and score < threshold
                for label, score in zip(labels, scores, strict=True)
            )
            / positives
        )
        false_positive_rate = (
            sum(
                label == 0 and score >= threshold
                for label, score in zip(labels, scores, strict=True)
            )
            / negatives
        )
        distance = abs(false_negative_rate - false_positive_rate)
        candidate = (distance, 0.5 * (false_negative_rate + false_positive_rate), threshold)
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    return best[1], best[2]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark raw CSD and CSD+ CSLS creator-profile style retrieval."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--csls-k", type=int, default=None)
    parser.add_argument("--require-learned", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    base = args.manifest.parent

    settings = Settings()
    router = StyleEmbeddingRouter(
        mode=settings.style_provider,
        csd_repo_path=settings.style_csd_repo_path,
        csd_model_path=settings.style_csd_model_path,
        device=settings.style_device,
        allow_legacy_pickle=settings.style_allow_legacy_pickle,
        expected_sha256=settings.style_csd_expected_sha256,
    )
    references = manifest.get("references") or []
    queries = manifest.get("queries") or []
    if len(references) < 3 or not queries:
        raise SystemExit("Manifest needs at least three references and one query.")

    first_vector = router.embed(_image(base / references[0]["path"]))
    provider = router.active
    if args.require_learned and not provider.learned:
        raise SystemExit(f"Learned style provider inactive: {router.fallback_reason}")

    vectors: dict[str, np.ndarray] = {"ref-0": normalize(first_vector)}
    groups: dict[str, list[str]] = defaultdict(list)
    groups[references[0]["creator"]].append("ref-0")
    for index, item in enumerate(references[1:], start=1):
        item_id = f"ref-{index}"
        vectors[item_id] = normalize(provider.embed(_image(base / item["path"])))
        groups[item["creator"]].append(item_id)
    if len(groups) < 2:
        raise SystemExit("Manifest needs references from at least two creators.")

    csls_k = args.csls_k or settings.style_csls_k
    raw_top1 = 0
    csls_top1 = 0
    raw_recall_k = 0
    csls_recall_k = 0
    labels: list[int] = []
    raw_verification_scores: list[float] = []
    csls_verification_scores: list[float] = []
    query_rows: list[dict] = []

    for item in queries:
        query = normalize(provider.embed(_image(base / item["path"])))
        readouts = corpus_profile_readout(query, vectors, groups, csls_k=csls_k)
        raw_ranked = sorted(
            ((creator, float(row["raw_pool_similarity"])) for creator, row in readouts.items()),
            key=lambda pair: (-pair[1], pair[0]),
        )
        csls_ranked = sorted(
            ((creator, float(row["csls_score"])) for creator, row in readouts.items()),
            key=lambda pair: (-pair[1], pair[0]),
        )
        expected = item["expected_creator"]
        raw_top1 += int(raw_ranked[0][0] == expected)
        csls_top1 += int(csls_ranked[0][0] == expected)
        raw_recall_k += int(expected in {creator for creator, _ in raw_ranked[: args.k]})
        csls_recall_k += int(expected in {creator for creator, _ in csls_ranked[: args.k]})
        for creator, row in readouts.items():
            labels.append(int(creator == expected))
            raw_verification_scores.append(float(row["raw_pool_similarity"]))
            csls_verification_scores.append(float(row["csls_score"]))
        query_rows.append(
            {
                "path": item["path"],
                "expected_creator": expected,
                "raw_top_creator": raw_ranked[0][0],
                "raw_top_score": round(raw_ranked[0][1], 6),
                "csls_top_creator": csls_ranked[0][0],
                "csls_top_score": round(csls_ranked[0][1], 6),
                "raw_correct": raw_ranked[0][0] == expected,
                "csls_correct": csls_ranked[0][0] == expected,
            }
        )

    gaps = aggregated_discrimination_gaps(vectors, groups)
    raw_eer = _equal_error_operating_point(labels, raw_verification_scores)
    csls_eer = _equal_error_operating_point(labels, csls_verification_scores)
    minimum_references_per_creator = min(len(member_ids) for member_ids in groups.values())
    promotion_eligible = bool(
        len(references) >= 15
        and len(groups) >= 5
        and minimum_references_per_creator >= 3
        and len(queries) >= 20
    )
    result = {
        "schema": "creatorproof.style_benchmark.v2",
        "provider": provider.name,
        "learned": bool(provider.learned),
        "reference_count": len(references),
        "creator_count": len(groups),
        "query_count": len(queries),
        "evaluation_grade": ("HELD_OUT_EVALUATION" if promotion_eligible else "SMOKE_TEST_ONLY"),
        "promotion_eligible": promotion_eligible,
        "minimum_support_gate": {
            "references": 15,
            "creators": 5,
            "references_per_creator": 3,
            "queries": 20,
        },
        "csls_k": csls_k,
        "raw_pool_cosine": {
            "top1_creator_accuracy": round(raw_top1 / len(queries), 6),
            f"recall_at_{args.k}": round(raw_recall_k / len(queries), 6),
            "verification_roc_auc": _roc_auc(labels, raw_verification_scores),
            "dataset_specific_equal_error_rate": raw_eer[0] if raw_eer else None,
            "dataset_specific_equal_error_threshold": raw_eer[1] if raw_eer else None,
        },
        "csd_plus_csls": {
            "top1_creator_accuracy": round(csls_top1 / len(queries), 6),
            f"recall_at_{args.k}": round(csls_recall_k / len(queries), 6),
            "verification_roc_auc": _roc_auc(labels, csls_verification_scores),
            "dataset_specific_equal_error_rate": csls_eer[0] if csls_eer else None,
            "dataset_specific_equal_error_threshold": csls_eer[1] if csls_eer else None,
        },
        "creator_discrimination": {
            creator: {
                key: round(float(value), 6) if isinstance(value, float) else value
                for key, value in row.items()
            }
            for creator, row in gaps.items()
        },
        "negative_discrimination_gap_count": sum(
            row["discrimination_gap"] is not None and row["discrimination_gap"] <= 0
            for row in gaps.values()
        ),
        "queries": query_rows,
        "calibration_state": "HELD_OUT_CORPUS_BENCHMARK_NOT_UNIVERSAL_CALIBRATION",
        "warning": (
            "All thresholds and error rates are specific to this manifest. Use creator-disjoint "
            "held-out data and difficult same-tradition negatives before deployment. Neither raw "
            "cosine nor CSLS is a probability or an infringement determination. "
            + (
                "This run does not meet the minimum support gate and must not be presented as "
                "accuracy validation."
                if not promotion_eligible
                else "This gate checks sample support, not dataset independence or quality."
            )
        ),
    }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
