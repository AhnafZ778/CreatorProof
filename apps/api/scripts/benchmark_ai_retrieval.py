"""Small, transparent retrieval benchmark for a local CreatorProof image set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from app.providers.ai_retrieval import SSCDVisualEmbeddingProvider


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
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text())
    provider = SSCDVisualEmbeddingProvider(args.model)
    if not provider.available:
        raise SystemExit(json.dumps(provider.status(), indent=2))

    references = {
        item["id"]: provider.embed(load_image((args.manifest.parent / item["path"]).resolve()))
        for item in manifest["references"]
    }
    total_positive = 0
    top1_correct = 0
    top5_correct = 0
    negative_count = 0
    negative_false_alerts = 0
    rows: list[dict] = []

    for query in manifest["queries"]:
        vector = provider.embed(load_image((args.manifest.parent / query["path"]).resolve()))
        ranking = sorted(
            (
                (reference_id, provider.similarity(vector, reference_vector))
                for reference_id, reference_vector in references.items()
            ),
            key=lambda row: (-row[1], row[0]),
        )
        expected = query.get("expected_reference_id")
        top_id, top_similarity = ranking[0]
        if expected:
            total_positive += 1
            top1_correct += int(top_id == expected)
            top5_correct += int(expected in {item[0] for item in ranking[:5]})
        else:
            negative_count += 1
            negative_false_alerts += int(top_similarity >= args.threshold)
        rows.append(
            {
                "query": query["path"],
                "expected": expected,
                "top_reference": top_id,
                "top_similarity": round(top_similarity, 6),
            }
        )

    report = {
        "provider": provider.name,
        "evaluation_grade": (
            "HELD_OUT_EVALUATION"
            if total_positive >= 20 and negative_count >= 20 and len(references) >= 10
            else "SMOKE_TEST_ONLY"
        ),
        "promotion_eligible": bool(
            total_positive >= 20 and negative_count >= 20 and len(references) >= 10
        ),
        "minimum_support_gate": {
            "references": 10,
            "positive_queries": 20,
            "negative_queries": 20,
        },
        "positive_queries": total_positive,
        "top1_accuracy": round(top1_correct / total_positive, 6) if total_positive else None,
        "recall_at_5": round(top5_correct / total_positive, 6) if total_positive else None,
        "negative_queries": negative_count,
        "negative_false_alert_rate_at_threshold": round(negative_false_alerts / negative_count, 6)
        if negative_count
        else None,
        "threshold": args.threshold,
        "rows": rows,
        "warning": (
            "A smoke test is not accuracy validation. Use transform- and source-disjoint queries."
        ),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
