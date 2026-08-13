"""Benchmark CreatorProof v0.5 copy fusion on labeled image pairs.

Manifest format:
{
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
from app.services.copy_fusion import fuse_copy_evidence


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
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise SystemExit("Manifest must contain a non-empty 'cases' list")

    settings = Settings()
    geometry_provider = ORBGeometricVerifier()
    aligned_provider = AlignedPerceptualVerifier()
    sscd = SSCDVisualEmbeddingProvider(args.model, args.device)
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
        aligned = asdict(aligned_provider.verify(query, reference, alignment))
        fusion = fuse_copy_evidence(
            exact_sha256=exact,
            ai_similarity=ai_similarity,
            phash_similarity=phash_similarity,
            geometry=geometry,
            aligned_perceptual=aligned,
            settings=settings,
        )
        label = bool(case["label"])
        records.append(
            {
                "case": case.get("id", f"case-{index:04d}"),
                "label": label,
                "predicted_match": fusion.match_supported,
                "review": fusion.review_supported,
                "ai_similarity": round(ai_similarity, 6) if ai_similarity is not None else None,
                "phash_similarity": round(phash_similarity, 6),
                "geometry_validated": geometry["validated"],
                "geometry_quality": fusion.geometry_quality,
                "structure_consensus": aligned["structure_consensus"],
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
    promotion_eligible = positives >= 20 and negatives >= 20
    output = {
        "schema": "creatorproof.copy_benchmark.v1",
        "sscd_provider": sscd.name,
        "sscd_available": sscd.available,
        "geometry_provider": geometry_provider.name,
        "aligned_provider": aligned_provider.name,
        "cases": len(records),
        "evaluation_grade": ("HELD_OUT_EVALUATION" if promotion_eligible else "SMOKE_TEST_ONLY"),
        "promotion_eligible": promotion_eligible,
        "minimum_support_gate": {"positive_pairs": 20, "hard_negative_pairs": 20},
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
        "records": records,
        "warning": (
            "The run is a smoke test and must not be reported as accuracy validation."
            if not promotion_eligible
            else "The sample gate does not replace source-, creator-, and transform-disjoint data."
        ),
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
