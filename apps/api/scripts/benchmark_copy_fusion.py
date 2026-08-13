"""Benchmark CreatorProof v0.5 copy fusion on labeled image pairs.

Manifest format:
{
  "corpus_manifest_paths": ["corpus/copy-test.v1.json"],
  "cases": [
    {"query": "queries/a.jpg", "reference": "refs/a.jpg", "label": true},
    {"query": "queries/x.jpg", "reference": "refs/a.jpg", "label": false}
  ]
}

Paths are resolved relative to the manifest. When the SSCD runtime is available the
script embeds both images directly; otherwise an optional per-case `ai_similarity`
can be supplied. Output is JSON on stdout and no benchmark asset is modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import imagehash
from PIL import Image

from app.core.config import Settings
from app.providers.ai_retrieval import SSCDVisualEmbeddingProvider
from app.providers.aligned_perceptual import AlignedPerceptualVerifier
from app.providers.geometry import ORBGeometricVerifier
from app.services.benchmark_manifest import (
    benchmark_run_identity,
    bind_benchmark_input_to_corpus,
    corpus_asset_binding,
    seal_benchmark_report,
)
from app.services.benchmark_statistics import binary_rate, lineage_cluster_bootstrap_interval
from app.services.copy_fusion import fuse_copy_evidence
from app.services.model_bundle import load_model_bundle


def _wilson(successes: int, total: int, z: float = 1.96) -> list[float] | None:
    if total <= 0:
        return None
    rate = successes / total
    denominator = 1.0 + z**2 / total
    center = (rate + z**2 / (2 * total)) / denominator
    radius = z * ((rate * (1.0 - rate) / total + z**2 / (4 * total**2)) ** 0.5)
    return [max(0.0, center - radius / denominator), min(1.0, center + radius / denominator)]


def _auc(rows: list[tuple[float, bool]]) -> float | None:
    positives = [score for score, label in rows if label]
    negatives = [score for score, label in rows if not label]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1.0
            elif positive == negative:
                wins += 0.5
    return wins / (len(positives) * len(negatives))


def _average_precision(rows: list[tuple[float, bool]]) -> float | None:
    positive_count = sum(label for _score, label in rows)
    if not positive_count:
        return None
    ranked = sorted(rows, key=lambda item: item[0], reverse=True)
    true_positives = 0
    precision_sum = 0.0
    for rank, (_score, label) in enumerate(ranked, start=1):
        if label:
            true_positives += 1
            precision_sum += true_positives / rank
    return precision_sum / positive_count


def _load(path: Path) -> Image.Image:
    with Image.open(path) as opened:
        image = opened.convert("RGB")
        image.load()
    return image


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--model", type=Path, default=Path("models/sscd_disc_mixup.torchscript.pt"))
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--bootstrap-iterations", type=int, default=2000)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit("Manifest must contain a non-empty 'cases' list")
    corpus_integrity = bind_benchmark_input_to_corpus(
        benchmark_manifest_path=manifest_path,
        benchmark_payload=payload,
        lane="COPY",
        referenced_locations=[str(case[key]) for case in cases for key in ("query", "reference")],
    )

    settings = Settings()
    bundle = load_model_bundle(
        settings.model_bundle_path,
        strict=settings.model_bundle_strict,
    )
    geometry_provider = ORBGeometricVerifier()
    aligned_provider = AlignedPerceptualVerifier()
    sscd = SSCDVisualEmbeddingProvider(
        args.model,
        args.device,
        expected_sha256=(
            settings.sscd_expected_sha256 or bundle.declared_artifact_sha256("copy-retrieval-sscd")
        ),
    )
    root = manifest_path.parent

    records: list[dict] = []
    for index, case in enumerate(cases, start=1):
        query_path = (root / str(case["query"])).resolve()
        reference_path = (root / str(case["reference"])).resolve()
        query = _load(query_path)
        reference = _load(reference_path)
        query_raw = query_path.read_bytes()
        reference_raw = reference_path.read_bytes()
        exact = hashlib.sha256(query_raw).digest() == hashlib.sha256(reference_raw).digest()
        phash_distance = int(imagehash.phash(query) - imagehash.phash(reference))
        phash_similarity = max(0.0, 1.0 - phash_distance / 64.0)

        ai_similarity = case.get("ai_similarity")
        if sscd.available:
            query_embedding = sscd.embed(query)
            reference_embedding = sscd.embed(reference)
            ai_similarity = sscd.similarity(query_embedding, reference_embedding)
        ai_similarity = float(ai_similarity) if ai_similarity is not None else None

        geometry = asdict(geometry_provider.verify(query, reference))
        alignment = geometry["homography_query_to_reference"] if geometry["validated"] else None
        aligned = asdict(
            aligned_provider.verify(
                query,
                reference,
                alignment,
                geometry.get("regions") if alignment is not None else None,
            )
        )
        fusion = fuse_copy_evidence(
            exact_sha256=exact,
            ai_similarity=ai_similarity,
            phash_similarity=phash_similarity,
            geometry=geometry,
            aligned_perceptual=aligned,
            settings=settings,
        )
        label = bool(case["label"])
        binding = corpus_asset_binding(corpus_integrity, str(case["query"]))
        records.append(
            {
                "case": case.get("id", f"case-{index:04d}"),
                "asset_id": binding["asset_id"],
                "source_lineage_id": binding["source_lineage_id"],
                "cohorts": binding["cohorts"],
                "label": label,
                "predicted_match": fusion.match_supported,
                "review": fusion.review_supported,
                "ai_similarity": round(ai_similarity, 6) if ai_similarity is not None else None,
                "phash_similarity": round(phash_similarity, 6),
                "geometry_validated": geometry["validated"],
                "geometry_quality": fusion.geometry_quality,
                "structure_consensus": aligned["structure_consensus"],
                "structure_mask_policy": aligned["evaluation_mask_policy"],
                "support_region_count": aligned["support_region_count"],
                "evidence_index": fusion.evidence_index,
                "classification": fusion.classification,
            }
        )

    tp = sum(row["label"] and row["predicted_match"] for row in records)
    fn = sum(row["label"] and not row["predicted_match"] for row in records)
    fp = sum(not row["label"] and row["predicted_match"] for row in records)
    tn = sum(not row["label"] and not row["predicted_match"] for row in records)
    positives = tp + fn
    negatives = fp + tn
    predicted_positives = tp + fp
    intervals = {
        "recall": lineage_cluster_bootstrap_interval(
            records,
            lambda sample: binary_rate(
                sample,
                numerator=lambda row: row["predicted_match"],
                denominator=lambda row: row["label"],
            ),
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
        "precision": lineage_cluster_bootstrap_interval(
            records,
            lambda sample: binary_rate(
                sample,
                numerator=lambda row: row["label"],
                denominator=lambda row: row["predicted_match"],
            ),
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
        "false_positive_rate": lineage_cluster_bootstrap_interval(
            records,
            lambda sample: binary_rate(
                sample,
                numerator=lambda row: row["predicted_match"],
                denominator=lambda row: not row["label"],
            ),
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
        "review_rate": lineage_cluster_bootstrap_interval(
            records,
            lambda sample: binary_rate(sample, numerator=lambda row: row["review"]),
            iterations=args.bootstrap_iterations,
            minimum_clusters=10,
        ),
    }
    uncertainty_gate_passed = all(
        interval["eligible_for_acceptance"] for interval in intervals.values()
    )
    evaluation_eligible = bool(
        positives >= 20
        and negatives >= 20
        and uncertainty_gate_passed
        and corpus_integrity["evaluation_eligible"]
    )
    error_gallery = [
        {
            "case": row["case"],
            "asset_id": row["asset_id"],
            "source_lineage_id": row["source_lineage_id"],
            "cohorts": row["cohorts"],
            "error_type": (
                "FALSE_NEGATIVE"
                if row["label"] and not row["predicted_match"]
                else "FALSE_POSITIVE"
                if not row["label"] and row["predicted_match"]
                else "REVIEW_REQUIRED"
            ),
            "classification": row["classification"],
            "geometry_validated": row["geometry_validated"],
            "structure_consensus": row["structure_consensus"],
        }
        for row in records
        if row["label"] != row["predicted_match"] or row["review"]
    ]
    output = {
        "schema": "creatorproof.copy_benchmark.v2",
        "run_identity": benchmark_run_identity(
            lane="COPY",
            manifest_payload=payload,
            model_bundle=bundle,
            threshold_policy_id="creatorproof-copy-fusion-operating-points-v3",
            corpus_manifest_set_digest_sha256=corpus_integrity["manifest_set_digest_sha256"],
        ),
        "corpus_integrity": corpus_integrity,
        "sscd_provider": sscd.name,
        "sscd_status": sscd.status(),
        "sscd_available": sscd.available,
        "geometry_provider": geometry_provider.name,
        "aligned_provider": aligned_provider.name,
        "cases": len(records),
        "evaluation_grade": ("HELD_OUT_EVALUATION" if evaluation_eligible else "SMOKE_TEST_ONLY"),
        "evaluation_eligible": evaluation_eligible,
        "promotion_eligible": False,
        "promotion_decision": {
            "state": "NOT_EVALUATED",
            "reason_code": "ACCEPTANCE_POLICY_NOT_APPLIED",
            "acceptance_policy_digest_sha256": None,
        },
        "minimum_support_gate": {
            "positive_pairs": 20,
            "hard_negative_pairs": 20,
            "source_lineage_clusters": 10,
        },
        "operating_configuration": {
            "fusion_policy_id": "creatorproof-copy-fusion-operating-points-v3",
            "settings_source": "CREATORPROOF_SETTINGS",
            "aligned_structure_mask_policy": "GEOMETRY_VERIFIED_SUPPORT_REGIONS_V1",
            "bootstrap_iterations": args.bootstrap_iterations,
        },
        "true_positive": tp,
        "false_negative": fn,
        "false_positive": fp,
        "true_negative": tn,
        "recall": tp / positives if positives else None,
        "precision": tp / predicted_positives if predicted_positives else None,
        "false_positive_rate": fp / negatives if negatives else None,
        "recall_wilson_95": _wilson(tp, positives),
        "false_positive_rate_wilson_95": _wilson(fp, negatives),
        "review_rate": sum(row["review"] for row in records) / len(records),
        "evidence_index_roc_auc": _auc([(row["evidence_index"], row["label"]) for row in records]),
        "evidence_index_average_precision": _average_precision(
            [(row["evidence_index"], row["label"]) for row in records]
        ),
        "lineage_clustered_confidence_intervals": intervals,
        "uncertainty_gate_passed": uncertainty_gate_passed,
        "error_gallery": error_gallery,
        "records": records,
        "warning": (
            "The run is a smoke test: valid TEST corpus binding and support gates are required."
            if not evaluation_eligible
            else "The sample gate does not replace source-, creator-, and transform-disjoint data."
        ),
    }
    output = seal_benchmark_report(output)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
