"""Small, transparent retrieval benchmark for a local CreatorProof image set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from app.core.config import Settings
from app.providers.ai_retrieval import SSCDVisualEmbeddingProvider
from app.services.benchmark_manifest import (
    benchmark_run_identity,
    bind_benchmark_input_to_corpus,
    corpus_asset_binding,
    seal_benchmark_report,
)
from app.services.benchmark_statistics import binary_rate, lineage_cluster_bootstrap_interval
from app.services.model_bundle import load_model_bundle
from app.services.retrieval import regional_query_views


def load_image(path: Path) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image.load()
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("models/sscd_disc_mixup.torchscript.pt"),
    )
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    corpus_integrity = bind_benchmark_input_to_corpus(
        benchmark_manifest_path=args.manifest,
        benchmark_payload=manifest,
        lane="COPY",
        referenced_locations=[
            str(item["path"])
            for item in [*(manifest.get("references") or []), *(manifest.get("queries") or [])]
        ],
    )
    settings = Settings()
    bundle = load_model_bundle(
        settings.model_bundle_path,
        strict=settings.model_bundle_strict,
    )
    provider = SSCDVisualEmbeddingProvider(
        args.model,
        expected_sha256=(
            settings.sscd_expected_sha256 or bundle.declared_artifact_sha256("copy-retrieval-sscd")
        ),
    )
    if not provider.available:
        raise SystemExit(json.dumps(provider.status(), indent=2))

    references = {
        item["id"]: provider.embed(load_image((args.manifest.parent / item["path"]).resolve()))
        for item in manifest["references"]
    }
    rows: list[dict] = []

    for query in manifest["queries"]:
        image = load_image((args.manifest.parent / query["path"]).resolve())
        views = regional_query_views(
            image,
            enabled=settings.copy_regional_retrieval_enabled,
            crop_fraction=settings.copy_regional_crop_fraction,
            minimum_short_side=settings.copy_regional_min_short_side,
        )
        vectors = provider.embed_many([view for _label, view in views])
        whole_ranking = sorted(
            (
                (reference_id, provider.similarity(vectors[0], reference_vector))
                for reference_id, reference_vector in references.items()
            ),
            key=lambda row: (-row[1], row[0]),
        )
        regional_ranking: list[tuple[str, float, str, float]] = []
        for reference_id, reference_vector in references.items():
            whole_similarity = provider.similarity(vectors[0], reference_vector)
            regional_scores = [
                (label, provider.similarity(vector, reference_vector))
                for (label, _view), vector in zip(views[1:], vectors[1:], strict=True)
            ]
            regional_label, regional_similarity = (
                max(regional_scores, key=lambda item: (item[1], item[0]))
                if regional_scores
                else ("whole_image", whole_similarity)
            )
            penalized_regional = regional_similarity - settings.copy_regional_similarity_penalty
            if penalized_regional > whole_similarity:
                retrieval_score = penalized_regional
                retrieval_view = regional_label
            else:
                retrieval_score = whole_similarity
                retrieval_view = "whole_image"
            regional_ranking.append(
                (reference_id, retrieval_score, retrieval_view, regional_similarity)
            )
        regional_ranking.sort(key=lambda row: (-row[1], row[0]))
        expected = query.get("expected_reference_id")
        whole_top_id, whole_top_similarity = whole_ranking[0]
        top_id, top_similarity, top_view, top_regional_similarity = regional_ranking[0]
        whole_expected_rank = next(
            (index for index, item in enumerate(whole_ranking, start=1) if item[0] == expected),
            None,
        )
        regional_expected_rank = next(
            (index for index, item in enumerate(regional_ranking, start=1) if item[0] == expected),
            None,
        )
        binding = corpus_asset_binding(corpus_integrity, str(query["path"]))
        rows.append(
            {
                "query": query["path"],
                "asset_id": binding["asset_id"],
                "source_lineage_id": binding["source_lineage_id"],
                "cohorts": binding["cohorts"],
                "expected": expected,
                "whole_image_top_reference": whole_top_id,
                "whole_image_top_similarity": round(whole_top_similarity, 6),
                "whole_image_expected_rank": whole_expected_rank,
                "top_reference": top_id,
                "top_similarity": round(top_similarity, 6),
                "top_retrieval_view": top_view,
                "top_regional_similarity": round(top_regional_similarity, 6),
                "regional_expected_rank": regional_expected_rank,
                "regional_query_count": max(0, len(views) - 1),
                "whole_image_negative_alert": bool(
                    expected is None and whole_top_similarity >= args.threshold
                ),
                "regional_negative_alert": bool(
                    expected is None and top_similarity >= args.threshold
                ),
            }
        )

    positives = [row for row in rows if row["expected"] is not None]
    negatives = [row for row in rows if row["expected"] is None]

    def rank_rate(field: str, depth: int):
        return lambda sample: binary_rate(
            sample,
            numerator=lambda row: row[field] is not None and int(row[field]) <= depth,
        )

    intervals = {
        "whole_image_recall_at_1": lineage_cluster_bootstrap_interval(
            positives,
            rank_rate("whole_image_expected_rank", 1),
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
        "regional_recall_at_1": lineage_cluster_bootstrap_interval(
            positives,
            rank_rate("regional_expected_rank", 1),
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
        "regional_recall_at_5": lineage_cluster_bootstrap_interval(
            positives,
            rank_rate("regional_expected_rank", 5),
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
        "regional_negative_false_alert_rate": lineage_cluster_bootstrap_interval(
            negatives,
            lambda sample: binary_rate(
                sample, numerator=lambda row: row["regional_negative_alert"]
            ),
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
    }
    support_gate_passed = bool(
        len(positives) >= 20 and len(negatives) >= 20 and len(references) >= 10
    )
    uncertainty_gate_passed = all(
        interval["eligible_for_acceptance"] for interval in intervals.values()
    )
    evaluation_eligible = bool(
        support_gate_passed and uncertainty_gate_passed and corpus_integrity["evaluation_eligible"]
    )
    whole_top1 = sum(row["whole_image_expected_rank"] == 1 for row in positives)
    regional_top1 = sum(row["regional_expected_rank"] == 1 for row in positives)
    regional_top5 = sum(
        row["regional_expected_rank"] is not None and row["regional_expected_rank"] <= 5
        for row in positives
    )
    regional_top10 = sum(
        row["regional_expected_rank"] is not None and row["regional_expected_rank"] <= 10
        for row in positives
    )
    whole_negative_alerts = sum(row["whole_image_negative_alert"] for row in negatives)
    regional_negative_alerts = sum(row["regional_negative_alert"] for row in negatives)
    report = {
        "schema": "creatorproof.copy_retrieval_benchmark.v2",
        "run_identity": benchmark_run_identity(
            lane="COPY",
            manifest_payload=manifest,
            model_bundle=bundle,
            threshold_policy_id="creatorproof-copy-retrieval-regional-operating-point-v2",
            corpus_manifest_set_digest_sha256=corpus_integrity["manifest_set_digest_sha256"],
        ),
        "corpus_integrity": corpus_integrity,
        "provider": provider.name,
        "provider_status": provider.status(),
        "evaluation_grade": ("HELD_OUT_EVALUATION" if evaluation_eligible else "SMOKE_TEST_ONLY"),
        "evaluation_eligible": evaluation_eligible,
        "promotion_eligible": False,
        "promotion_decision": {
            "state": "NOT_EVALUATED",
            "reason_code": "ACCEPTANCE_POLICY_NOT_APPLIED",
            "acceptance_policy_digest_sha256": None,
        },
        "minimum_support_gate": {
            "references": 10,
            "positive_queries": 20,
            "negative_queries": 20,
            "positive_source_lineages": 10,
            "negative_source_lineages": 10,
        },
        "positive_queries": len(positives),
        "whole_image_baseline": {
            "top1_accuracy": round(whole_top1 / len(positives), 6) if positives else None,
            "negative_false_alert_rate_at_threshold": (
                round(whole_negative_alerts / len(negatives), 6) if negatives else None
            ),
        },
        "regional_candidate_retrieval": {
            "top1_accuracy": round(regional_top1 / len(positives), 6) if positives else None,
            "recall_at_5": round(regional_top5 / len(positives), 6) if positives else None,
            "recall_at_10": round(regional_top10 / len(positives), 6) if positives else None,
            "mean_reciprocal_rank": (
                round(
                    sum(1.0 / row["regional_expected_rank"] for row in positives) / len(positives),
                    6,
                )
                if positives and all(row["regional_expected_rank"] for row in positives)
                else None
            ),
            "negative_false_alert_rate_at_threshold": (
                round(regional_negative_alerts / len(negatives), 6) if negatives else None
            ),
        },
        # Compatibility metrics now represent the deployed regional nomination policy.
        "top1_accuracy": round(regional_top1 / len(positives), 6) if positives else None,
        "recall_at_5": round(regional_top5 / len(positives), 6) if positives else None,
        "negative_queries": len(negatives),
        "negative_false_alert_rate_at_threshold": (
            round(regional_negative_alerts / len(negatives), 6) if negatives else None
        ),
        "lineage_clustered_confidence_intervals": intervals,
        "uncertainty_gate_passed": uncertainty_gate_passed,
        "threshold": args.threshold,
        "operating_configuration": {
            "negative_alert_threshold": args.threshold,
            "retrieval_depths": [1, 5, 10],
            "regional_query_policy": "SSCD_WHOLE_PLUS_FIVE_OVERLAPPING_REGIONS_V1",
            "regional_crop_fraction": settings.copy_regional_crop_fraction,
            "regional_minimum_short_side": settings.copy_regional_min_short_side,
            "regional_similarity_penalty": settings.copy_regional_similarity_penalty,
            "bootstrap_iterations": args.bootstrap_iterations,
        },
        "rows": rows,
        "warning": (
            "A smoke test is not accuracy validation. A valid TEST corpus binding, "
            "transform/source controls, and the minimum support gate are all required."
            if not evaluation_eligible
            else "Sample support does not replace manual lineage and hard-negative review."
        ),
    }
    report = seal_benchmark_report(report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
