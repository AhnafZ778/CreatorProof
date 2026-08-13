from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

from app.core.config import Settings
from app.providers.style_retrieval import StyleEmbeddingRouter
from app.services.benchmark_manifest import (
    benchmark_run_identity,
    bind_benchmark_input_to_corpus,
    corpus_asset_binding,
    seal_benchmark_report,
)
from app.services.benchmark_statistics import binary_rate, lineage_cluster_bootstrap_interval
from app.services.model_bundle import load_model_bundle
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


def _average_precision(labels: list[int], scores: list[float]) -> float | None:
    positive_count = sum(labels)
    if not positive_count:
        return None
    ranked = sorted(zip(scores, labels, strict=True), key=lambda item: item[0], reverse=True)
    true_positives = 0
    precision_sum = 0.0
    for rank, (_score, label) in enumerate(ranked, start=1):
        if label:
            true_positives += 1
            precision_sum += true_positives / rank
    return precision_sum / positive_count


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
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    base = args.manifest.parent

    settings = Settings()
    bundle = load_model_bundle(
        settings.model_bundle_path,
        strict=settings.model_bundle_strict,
    )
    router = StyleEmbeddingRouter(
        mode=settings.style_provider,
        csd_repo_path=settings.style_csd_repo_path,
        csd_model_path=settings.style_csd_model_path,
        device=settings.style_device,
        allow_legacy_pickle=settings.style_allow_legacy_pickle,
        expected_sha256=(
            settings.style_csd_expected_sha256 or bundle.declared_artifact_sha256("style-csd")
        ),
        expected_repo_revision=settings.style_csd_expected_repo_revision,
    )
    references = manifest.get("references") or []
    queries = manifest.get("queries") or []
    if len(references) < 3 or not queries:
        raise SystemExit("Manifest needs at least three references and one query.")
    corpus_integrity = bind_benchmark_input_to_corpus(
        benchmark_manifest_path=args.manifest,
        benchmark_payload=manifest,
        lane="CREATOR_PROFILE",
        referenced_locations=[str(item["path"]) for item in [*references, *queries]],
    )

    reference_images = [_image(base / item["path"]) for item in references]
    first_vector = router.embed(reference_images[0])
    provider = router.active
    if args.require_learned and not provider.learned:
        raise SystemExit(f"Learned style provider inactive: {router.fallback_reason}")

    remaining_vectors = (
        provider.embed_many(reference_images[1:])
        if hasattr(provider, "embed_many")
        else [provider.embed(image) for image in reference_images[1:]]
    )
    reference_vectors = [first_vector, *remaining_vectors]
    vectors: dict[str, np.ndarray] = {"ref-0": normalize(reference_vectors[0])}
    groups: dict[str, list[str]] = defaultdict(list)
    groups[references[0]["creator"]].append("ref-0")
    for index, item in enumerate(references[1:], start=1):
        item_id = f"ref-{index}"
        vectors[item_id] = normalize(reference_vectors[index])
        groups[item["creator"]].append(item_id)
    if len(groups) < 2:
        raise SystemExit("Manifest needs references from at least two creators.")

    csls_k = args.csls_k or settings.style_csls_k
    labels: list[int] = []
    raw_verification_scores: list[float] = []
    csls_verification_scores: list[float] = []
    verification_rows: list[dict] = []
    query_rows: list[dict] = []
    open_set_operating_point = manifest.get("open_set_operating_point") or {}
    open_set_threshold = open_set_operating_point.get("csls_threshold")
    open_set_policy_locked = bool(
        isinstance(open_set_threshold, (int, float))
        and str(open_set_operating_point.get("selected_on_partition")) == "CALIBRATION"
        and str(open_set_operating_point.get("policy_id") or "").strip()
    )
    open_set_threshold = float(open_set_threshold) if open_set_policy_locked else None

    query_images = [_image(base / item["path"]) for item in queries]
    query_vectors = (
        provider.embed_many(query_images)
        if hasattr(provider, "embed_many")
        else [provider.embed(image) for image in query_images]
    )
    for item, query_vector in zip(queries, query_vectors, strict=True):
        query = normalize(query_vector)
        readouts = corpus_profile_readout(query, vectors, groups, csls_k=csls_k)
        raw_ranked = sorted(
            ((creator, float(row["raw_pool_similarity"])) for creator, row in readouts.items()),
            key=lambda pair: (-pair[1], pair[0]),
        )
        csls_ranked = sorted(
            ((creator, float(row["csls_score"])) for creator, row in readouts.items()),
            key=lambda pair: (-pair[1], pair[0]),
        )
        expected = item.get("expected_creator")
        known_creator = bool(expected)
        binding = corpus_asset_binding(corpus_integrity, str(item["path"]))
        creator_cluster_id = (
            f"creator:{expected}"
            if known_creator
            else f"unknown-lineage:{binding['source_lineage_id']}"
        )
        for creator, row in readouts.items():
            labels.append(int(creator == expected))
            raw_verification_scores.append(float(row["raw_pool_similarity"]))
            csls_verification_scores.append(float(row["csls_score"]))
            verification_rows.append(
                {
                    "creator_cluster_id": creator_cluster_id,
                    "source_lineage_id": binding["source_lineage_id"],
                    "label": int(creator == expected),
                    "raw_score": float(row["raw_pool_similarity"]),
                    "csls_score": float(row["csls_score"]),
                }
            )
        open_set_rejected = (
            csls_ranked[0][1] < open_set_threshold if open_set_threshold is not None else None
        )
        query_rows.append(
            {
                "path": item["path"],
                "asset_id": binding["asset_id"],
                "source_lineage_id": binding["source_lineage_id"],
                "creator_cluster_id": creator_cluster_id,
                "cohorts": binding["cohorts"],
                "expected_creator": expected,
                "known_creator": known_creator,
                "raw_top_creator": raw_ranked[0][0],
                "raw_top_score": round(raw_ranked[0][1], 6),
                "csls_top_creator": csls_ranked[0][0],
                "csls_top_score": round(csls_ranked[0][1], 6),
                "raw_correct": bool(known_creator and raw_ranked[0][0] == expected),
                "csls_correct": bool(known_creator and csls_ranked[0][0] == expected),
                "raw_expected_rank": (
                    next(
                        index
                        for index, (creator, _score) in enumerate(raw_ranked, start=1)
                        if creator == expected
                    )
                    if known_creator
                    else None
                ),
                "csls_expected_rank": (
                    next(
                        index
                        for index, (creator, _score) in enumerate(csls_ranked, start=1)
                        if creator == expected
                    )
                    if known_creator
                    else None
                ),
                "open_set_rejected": open_set_rejected,
                "open_set_decision_correct": (
                    (
                        open_set_rejected
                        if not known_creator
                        else not open_set_rejected and csls_ranked[0][0] == expected
                    )
                    if open_set_rejected is not None
                    else None
                ),
            }
        )

    gaps = aggregated_discrimination_gaps(vectors, groups)
    raw_eer = _equal_error_operating_point(labels, raw_verification_scores)
    csls_eer = _equal_error_operating_point(labels, csls_verification_scores)
    minimum_references_per_creator = min(len(member_ids) for member_ids in groups.values())
    known_queries = [row for row in query_rows if row["known_creator"]]
    unknown_queries = [row for row in query_rows if not row["known_creator"]]

    def rank_rate(field: str, depth: int):
        return lambda sample: binary_rate(
            sample,
            numerator=lambda row: row[field] is not None and int(row[field]) <= depth,
        )

    intervals = {
        "csls_top1_creator_accuracy": lineage_cluster_bootstrap_interval(
            known_queries,
            rank_rate("csls_expected_rank", 1),
            cluster_field="creator_cluster_id",
            iterations=args.bootstrap_iterations,
            minimum_clusters=5,
        ),
        f"csls_recall_at_{args.k}": lineage_cluster_bootstrap_interval(
            known_queries,
            rank_rate("csls_expected_rank", args.k),
            cluster_field="creator_cluster_id",
            iterations=args.bootstrap_iterations,
            minimum_clusters=5,
        ),
        "open_set_unknown_rejection_rate": lineage_cluster_bootstrap_interval(
            unknown_queries,
            lambda sample: binary_rate(
                sample, numerator=lambda row: bool(row["open_set_rejected"])
            ),
            cluster_field="creator_cluster_id",
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
        "csls_verification_roc_auc": lineage_cluster_bootstrap_interval(
            verification_rows,
            lambda sample: _roc_auc(
                [int(row["label"]) for row in sample],
                [float(row["csls_score"]) for row in sample],
            ),
            cluster_field="creator_cluster_id",
            iterations=args.bootstrap_iterations,
            minimum_clusters=5,
        ),
    }
    uncertainty_gate_passed = all(
        interval["eligible_for_acceptance"] for interval in intervals.values()
    )
    evaluation_eligible = bool(
        len(references) >= 15
        and len(groups) >= 5
        and minimum_references_per_creator >= 3
        and len(known_queries) >= 20
        and len(unknown_queries) >= 20
        and manifest.get("creator_disjoint") is True
        and open_set_policy_locked
        and uncertainty_gate_passed
        and corpus_integrity["evaluation_eligible"]
    )
    raw_top1 = sum(row["raw_expected_rank"] == 1 for row in known_queries)
    csls_top1 = sum(row["csls_expected_rank"] == 1 for row in known_queries)
    raw_recall_k = sum(
        row["raw_expected_rank"] is not None and row["raw_expected_rank"] <= args.k
        for row in known_queries
    )
    csls_recall_k = sum(
        row["csls_expected_rank"] is not None and row["csls_expected_rank"] <= args.k
        for row in known_queries
    )
    error_gallery = [
        {
            "path": row["path"],
            "asset_id": row["asset_id"],
            "source_lineage_id": row["source_lineage_id"],
            "cohorts": row["cohorts"],
            "error_type": (
                "KNOWN_CREATOR_RETRIEVAL_MISS"
                if row["known_creator"] and not row["csls_correct"]
                else "UNKNOWN_CREATOR_FALSE_ACCEPT"
            ),
            "expected_creator": row["expected_creator"],
            "top_creator": row["csls_top_creator"],
            "top_score": row["csls_top_score"],
        }
        for row in query_rows
        if (row["known_creator"] and not row["csls_correct"])
        or (not row["known_creator"] and row["open_set_rejected"] is False)
    ]
    result = {
        "schema": "creatorproof.style_benchmark.v3",
        "run_identity": benchmark_run_identity(
            lane="CREATOR_PROFILE",
            manifest_payload=manifest,
            model_bundle=bundle,
            threshold_policy_id="creatorproof-style-csd-plus-open-set-readout-v3",
            corpus_manifest_set_digest_sha256=corpus_integrity["manifest_set_digest_sha256"],
        ),
        "corpus_integrity": corpus_integrity,
        "provider": provider.name,
        "provider_status": router.status(),
        "learned": bool(provider.learned),
        "reference_count": len(references),
        "creator_count": len(groups),
        "query_count": len(queries),
        "known_query_count": len(known_queries),
        "unknown_query_count": len(unknown_queries),
        "evaluation_grade": ("HELD_OUT_EVALUATION" if evaluation_eligible else "SMOKE_TEST_ONLY"),
        "evaluation_eligible": evaluation_eligible,
        "promotion_eligible": False,
        "promotion_decision": {
            "state": "NOT_EVALUATED",
            "reason_code": "ACCEPTANCE_POLICY_NOT_APPLIED",
            "acceptance_policy_digest_sha256": None,
        },
        "minimum_support_gate": {
            "references": 15,
            "creators": 5,
            "references_per_creator": 3,
            "queries": 20,
            "unknown_queries": 20,
            "creator_disjoint": True,
            "creator_clusters": 5,
            "unknown_source_lineages": 10,
        },
        "csls_k": csls_k,
        "operating_configuration": {
            "readout_policy_id": "creatorproof-style-csd-plus-open-set-readout-v3",
            "csls_k": csls_k,
            "recall_depth": args.k,
            "open_set_operating_point": open_set_operating_point,
            "open_set_policy_locked": open_set_policy_locked,
            "bootstrap_iterations": args.bootstrap_iterations,
        },
        "raw_pool_cosine": {
            "top1_creator_accuracy": round(raw_top1 / len(known_queries), 6)
            if known_queries
            else None,
            f"recall_at_{args.k}": round(raw_recall_k / len(known_queries), 6)
            if known_queries
            else None,
            "verification_roc_auc": _roc_auc(labels, raw_verification_scores),
            "verification_average_precision": _average_precision(labels, raw_verification_scores),
            "dataset_specific_equal_error_rate": raw_eer[0] if raw_eer else None,
            "dataset_specific_equal_error_threshold": raw_eer[1] if raw_eer else None,
        },
        "csd_plus_csls": {
            "top1_creator_accuracy": round(csls_top1 / len(known_queries), 6)
            if known_queries
            else None,
            f"recall_at_{args.k}": round(csls_recall_k / len(known_queries), 6)
            if known_queries
            else None,
            "verification_roc_auc": _roc_auc(labels, csls_verification_scores),
            "verification_average_precision": _average_precision(labels, csls_verification_scores),
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
        "open_set": {
            "policy_locked_on_calibration": open_set_policy_locked,
            "threshold": open_set_threshold,
            "unknown_rejection_rate": (
                sum(bool(row["open_set_rejected"]) for row in unknown_queries)
                / len(unknown_queries)
                if unknown_queries and open_set_policy_locked
                else None
            ),
            "known_acceptance_rate": (
                sum(not bool(row["open_set_rejected"]) for row in known_queries)
                / len(known_queries)
                if known_queries and open_set_policy_locked
                else None
            ),
        },
        "creator_clustered_confidence_intervals": intervals,
        "uncertainty_gate_passed": uncertainty_gate_passed,
        "error_gallery": error_gallery,
        "queries": query_rows,
        "calibration_state": "HELD_OUT_CORPUS_BENCHMARK_NOT_UNIVERSAL_CALIBRATION",
        "warning": (
            "All thresholds and error rates are specific to this manifest. Use creator-disjoint "
            "held-out data and difficult same-tradition negatives before deployment. Neither raw "
            "cosine nor CSLS is a probability or an infringement determination. "
            + (
                "This run lacks a valid TEST corpus binding or minimum support and must not be "
                "presented as accuracy validation."
                if not evaluation_eligible
                else "This gate checks sample support, not dataset independence or quality."
            )
        ),
    }
    result = seal_benchmark_report(result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
