"""Deterministic generated-media stress test for before/after behavior.

This suite is intentionally not a real-world accuracy benchmark. It uses generated
geometric artwork to compare algorithms on fixed partial-copy, collage, and statistical
selection scenarios without claiming corpus authorization or deployment validity.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from app.core.config import Settings
from app.providers.ai_retrieval import SSCDVisualEmbeddingProvider
from app.providers.aligned_perceptual import AlignedPerceptualVerifier
from app.services.model_bundle import canonical_json_digest, load_model_bundle
from app.services.retrieval import regional_query_views
from app.services.style_readout import catalog_relative_empirical_support, normalize


def _artwork(seed: int) -> Image.Image:
    rng = np.random.default_rng(seed)
    image = Image.new(
        "RGB",
        (320, 320),
        tuple(int(value) for value in rng.integers(20, 230, 3)),
    )
    draw = ImageDraw.Draw(image)
    for index in range(24):
        left, top = (int(value) for value in rng.integers(0, 280, 2))
        width, height = (int(value) for value in rng.integers(15, 90, 2))
        color = tuple(int(value) for value in rng.integers(0, 256, 3))
        box = (left, top, min(319, left + width), min(319, top + height))
        if index % 3 == 0:
            draw.ellipse(box, fill=color, outline="white", width=2)
        elif index % 3 == 1:
            draw.rectangle(box, fill=color, outline="black", width=2)
        else:
            draw.line(box, fill=color, width=5)
    draw.text(
        (15, 285),
        f"CREATOR {seed:02d}",
        fill="white",
        stroke_width=2,
        stroke_fill="black",
    )
    return image


def _collage(images: list[Image.Image]) -> Image.Image:
    result = Image.new("RGB", (640, 640))
    for image, position in zip(
        images,
        ((0, 0), (320, 0), (0, 320), (320, 320)),
        strict=True,
    ):
        result.paste(image, position)
    return result


def _retrieval_stress(provider, settings) -> dict:
    references = [_artwork(seed) for seed in range(24)]
    reference_vectors = provider.embed_many(references)
    rows: list[dict] = []
    for group_index in range(6):
        expected = list(range(group_index * 4, group_index * 4 + 4))
        query = _collage([references[index] for index in expected])
        views = regional_query_views(
            query,
            enabled=True,
            crop_fraction=settings.copy_regional_crop_fraction,
            minimum_short_side=settings.copy_regional_min_short_side,
        )
        vectors = provider.embed_many([image for _label, image in views])
        whole = sorted(
            (
                (index, provider.similarity(vectors[0], reference_vector))
                for index, reference_vector in enumerate(reference_vectors)
            ),
            key=lambda item: (-item[1], item[0]),
        )
        regional: list[tuple[int, float, str]] = []
        for index, reference_vector in enumerate(reference_vectors):
            view_scores = [
                (label, provider.similarity(vector, reference_vector))
                for (label, _image), vector in zip(views, vectors, strict=True)
            ]
            label, score = max(view_scores, key=lambda item: (item[1], item[0]))
            adjusted = score - (
                settings.copy_regional_similarity_penalty if label != "whole_image" else 0.0
            )
            regional.append((index, adjusted, label))
        regional.sort(key=lambda item: (-item[1], item[0]))
        expected_set = set(expected)
        whole_found = len({index for index, _score in whole[:4]} & expected_set)
        regional_found = len({index for index, _score, _label in regional[:4]} & expected_set)
        rows.append(
            {
                "collage_id": f"generated-collage-{group_index + 1:02d}",
                "expected_reference_ids": expected,
                "whole_image_top4": [index for index, _score in whole[:4]],
                "regional_top4": [index for index, _score, _label in regional[:4]],
                "whole_image_source_coverage_at_4": whole_found / 4.0,
                "regional_source_coverage_at_4": regional_found / 4.0,
            }
        )
    baseline = float(np.mean([row["whole_image_source_coverage_at_4"] for row in rows]))
    improved = float(np.mean([row["regional_source_coverage_at_4"] for row in rows]))
    return {
        "scenario": "FOUR_SOURCE_COLLAGE_RETRIEVAL",
        "reference_count": len(references),
        "collage_count": len(rows),
        "baseline_policy": "WHOLE_IMAGE_SSCD_ONLY",
        "improved_policy": "WHOLE_PLUS_FIVE_OVERLAPPING_REGIONS_WITH_PENALTY",
        "baseline_source_coverage_at_4": baseline,
        "improved_source_coverage_at_4": improved,
        "absolute_improvement_percentage_points": (improved - baseline) * 100.0,
        "relative_improvement_percent": (
            ((improved - baseline) / baseline) * 100.0 if baseline > 0 else None
        ),
        "rows": rows,
    }


def _structural_stress() -> dict:
    reference = _artwork(778)
    reference_array = np.asarray(reference, dtype=np.uint8)
    rng = np.random.default_rng(778)
    query_array = rng.integers(0, 256, size=reference_array.shape, dtype=np.uint8)
    left, top, right, bottom = 52, 48, 274, 184
    query_array[top:bottom, left:right] = reference_array[top:bottom, left:right]
    query = Image.fromarray(query_array)
    identity = (
        (1.0, 0.0, 0.0),
        (0.0, 1.0, 0.0),
        (0.0, 0.0, 1.0),
    )
    verifier = AlignedPerceptualVerifier()
    baseline = asdict(verifier.verify(query, reference, identity))
    improved = asdict(
        verifier.verify(
            query,
            reference,
            identity,
            [
                {
                    "kind": "VERIFIED_SUPPORT_PATCH",
                    "reference_polygon": [
                        [left / 319, top / 319],
                        [right / 319, top / 319],
                        [right / 319, bottom / 319],
                        [left / 319, bottom / 319],
                    ],
                }
            ],
        )
    )
    baseline_score = float(baseline["structure_consensus"] or 0.0)
    improved_score = float(improved["structure_consensus"] or 0.0)
    return {
        "scenario": "PARTIAL_COPY_IN_UNRELATED_BACKGROUND_WITH_FIXED_ALIGNMENT",
        "baseline_mask_policy": baseline["evaluation_mask_policy"],
        "improved_mask_policy": improved["evaluation_mask_policy"],
        "baseline_structure_consensus": baseline_score,
        "improved_structure_consensus": improved_score,
        "absolute_improvement": improved_score - baseline_score,
        "relative_improvement_percent": (
            ((improved_score - baseline_score) / baseline_score) * 100.0
            if baseline_score > 0
            else None
        ),
        "note": "The alignment is fixed to isolate mask behavior; this is not geometry accuracy.",
    }


def _style_selection_stress() -> dict:
    vectors = {
        "a1": normalize(np.array([1.0, 0.02, 0.0])),
        "a2": normalize(np.array([0.99, -0.03, 0.0])),
        "a3": normalize(np.array([0.98, 0.04, 0.0])),
    }
    groups: dict[str, list[str]] = {"artist-a": ["a1", "a2", "a3"]}
    for index in range(20):
        item_id = f"negative-{index}"
        angle = index / 20 * np.pi
        vectors[item_id] = normalize(np.array([0.05, np.cos(angle), np.sin(angle)]))
        groups.setdefault("artist-b" if index < 10 else "artist-c", []).append(item_id)
    result = catalog_relative_empirical_support(
        0.97,
        vectors,
        groups,
        "artist-a",
        min_profile_works=3,
        min_profiles=3,
        min_negatives=19,
    )
    raw_passes_naive_gate = float(result["negative_tail_p_raw"]) <= 0.05
    adjusted_passes_gate = float(result["negative_tail_p"]) <= 0.05
    return {
        "scenario": "BEST_OF_MULTIPLE_CREATOR_PROFILES_SELECTION_BIAS",
        "raw_negative_tail_p": result["negative_tail_p_raw"],
        "selection_adjusted_negative_tail_p": result["negative_tail_p"],
        "selection_count": result["selection_count"],
        "naive_false_support_gate_passed": raw_passes_naive_gate,
        "corrected_support_gate_passed": adjusted_passes_gate,
        "false_support_prevented": raw_passes_naive_gate and not adjusted_passes_gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("models/sscd_disc_mixup.torchscript.pt"),
    )
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    settings = Settings()
    bundle = load_model_bundle(settings.model_bundle_path, strict=True)
    provider = SSCDVisualEmbeddingProvider(
        args.model,
        args.device,
        expected_sha256=(
            settings.sscd_expected_sha256 or bundle.declared_artifact_sha256("copy-retrieval-sscd")
        ),
    )
    if not provider.available:
        print(json.dumps({"valid": False, "provider": provider.status()}, indent=2))
        return 2
    result = {
        "schema": "creatorproof.generated_model_system_stress.v1",
        "evaluation_grade": "SYNTHETIC_STRESS_ONLY_NOT_REAL_WORLD_ACCURACY",
        "model_bundle": bundle.status(),
        "provider": provider.status(),
        "fixed_generation_policy": "NUMPY_PCG64_SEEDS_0_TO_23_AND_778_V1",
        "retrieval": _retrieval_stress(provider, settings),
        "region_aware_structure": _structural_stress(),
        "style_selection_control": _style_selection_stress(),
        "overall_real_world_accuracy_improvement_percent": None,
        "limitations": [
            "Generated geometric artwork does not represent the deployment distribution.",
            "The percentage applies only to four-source collage retrieval coverage in this suite.",
            "No origin-detector accuracy percentage is calculated without generator-disjoint data.",
            (
                "No creator-profile accuracy percentage is calculated without "
                "consented creator-disjoint data."
            ),
        ],
    }
    result["result_digest_sha256"] = canonical_json_digest(result)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
