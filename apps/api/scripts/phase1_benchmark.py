"""Lawful, reproducible Phase 1 fixture generator and backend benchmark.

No images are downloaded.  Procedural images are test artwork, not outputs of an
AI image-generation model.  An AI image-to-image cohort is unavailable unless
the operator supplies fixtures with an explicit authorization and generator
record.  The runner exercises the actual registration, scan and matrix APIs in
an isolated SQLite/local-storage application and never sends data to providers.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import mimetypes
import random
import shutil
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import median

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.benchmark_manifest import (  # noqa: E402
    benchmark_run_identity,
    bind_benchmark_input_to_corpus,
    load_corpus_manifest,
    seal_benchmark_report,
    validate_benchmark_report_payload,
)

API_ROOT = Path(__file__).resolve().parents[1]
TRANSFORM_GROUPS = (
    "EXACT_DUPLICATE",
    "JPEG_RECOMPRESSION",
    "RESIZE",
    "CROP",
    "MIRROR",
    "ROTATION",
    "OVERLAY",
    "TEXT_OVERLAY",
    "COLOR_SHIFT",
    "RECOLORING",
    "PARTIAL_REUSE",
    "SCREENSHOT",
)
NEGATIVE_GROUPS = (
    "UNRELATED_SIMILAR_SUBJECT",
    "SAME_SUBJECT_DIFFERENT_CREATOR_PROXY",
    "SAME_PALETTE_DIFFERENT_COMPOSITION",
    "STYLE_LIKE_NON_COPYING",
)
MATRIX_LANES = {
    "COPY",
    "ORIGIN",
    "PROVENANCE",
    "CREATOR_PROFILE",
    "RIGHTS",
    "POLICY",
    "SOURCE_COVERAGE",
    "INTEGRITY",
}


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _procedural_art(seed: int, *, composition: int = 0) -> Image.Image:
    rng = random.Random(seed)
    image = Image.new("RGB", (384, 320), (238, 241, 246))
    draw = ImageDraw.Draw(image)
    palette = [(22, 72, 160), (238, 127, 49), (68, 155, 119), (91, 59, 142)]
    # Same subject and palette, independently positioned/stroked geometry. The
    # negatives are independently constructed, never transformed source pixels.
    for index in range(36):
        x, y = rng.randint(12, 330), rng.randint(12, 267)
        if composition:
            x = (x + composition * 71) % 330 + 12
            y = (y + composition * 47) % 260 + 12
        size = rng.randint(8, 40)
        box = (x, y, min(383, x + size), min(319, y + size))
        if index % 3:
            draw.rectangle(box, fill=palette[index % 4], outline=(12, 18, 30), width=2)
        else:
            draw.ellipse(box, fill=palette[index % 4], outline=(12, 18, 30), width=2)
    for _ in range(95):
        x, y = rng.randint(0, 375), rng.randint(0, 311)
        draw.line(
            (x, y, x + rng.randint(3, 8), y + rng.randint(3, 8)),
            fill=tuple(rng.randint(10, 225) for _ in range(3)),
            width=2,
        )
    return image


def _transform(image: Image.Image, group: str) -> tuple[Image.Image, list[float] | None]:
    result = image.copy()
    if group == "JPEG_RECOMPRESSION":
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=55)
        buffer.seek(0)
        result = Image.open(buffer).convert("RGB")
    elif group == "RESIZE":
        result = image.resize((192, 160), Image.Resampling.LANCZOS)
    elif group == "CROP":
        result = image.crop((45, 35, 340, 275))
    elif group == "MIRROR":
        result = ImageOps.mirror(image)
    elif group == "ROTATION":
        result = image.rotate(8, resample=Image.Resampling.BICUBIC, expand=True)
    elif group in {"OVERLAY", "TEXT_OVERLAY"}:
        draw = ImageDraw.Draw(result)
        draw.rectangle((0, 280, 384, 320), fill=(15, 20, 32))
        if group == "TEXT_OVERLAY":
            draw.text((12, 292), "INTERNAL TEST ART - CONTROLLED REPOST", fill="white")
    elif group == "COLOR_SHIFT":
        result = ImageEnhance.Color(image).enhance(0.35)
    elif group == "RECOLORING":
        result = ImageOps.colorize(image.convert("L"), (8, 26, 57), (163, 222, 255))
    elif group == "PARTIAL_REUSE":
        # Known source support in the query is exactly this rectangle. The rest
        # of the candidate is independently generated rather than mislabeled.
        result = _procedural_art(7741)
        result.paste(image.crop((40, 35, 260, 230)), (100, 70))
        return result, [100 / 384, 70 / 320, 320 / 384, 265 / 320]
    elif group == "SCREENSHOT":
        result = Image.new("RGB", (424, 390), (28, 30, 38))
        ImageDraw.Draw(result).text((20, 13), "LOCAL TEST VIEWER", fill="white")
        result.paste(image, (20, 45))
        return result, [20 / 424, 45 / 390, 404 / 424, 365 / 390]
    return result, None


def _safe_fixture_path(root: Path, location: str) -> Path:
    relative = Path(location)
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError("Fixture paths must remain inside the manifest directory")
    if not path.is_file():
        raise ValueError(f"Fixture does not exist: {location}")
    return path


def generate_dataset(
    output: Path,
    *,
    source_count: int = 4,
    seed: int = 731,
    authorized_ai_fixtures: Path | None = None,
) -> Path:
    if not 1 <= source_count <= 40:
        raise ValueError("source_count must be between 1 and 40")
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "benchmark.json").exists():
        raise ValueError("Benchmark already exists; choose an empty output directory")
    (output / "images").mkdir(exist_ok=True)
    items: list[dict] = []
    cases: list[dict] = []
    references: list[str] = []

    def asset(
        location: str,
        *,
        lineage: str,
        group: str,
        match: bool,
        reference: str | None = None,
        rights: dict | None = None,
    ) -> None:
        if any(row["location"] == location for row in items):
            return
        row = {
            "asset_id": Path(location).stem,
            "location": location,
            "sha256": hashlib.sha256((output / location).read_bytes()).hexdigest(),
            "source_lineage_id": lineage,
            "exposure_state": "DEMO_EXPOSED",
            "rights": rights
            or {"state": "AUTHORIZED", "reference": "repository-procedural-fixture-generator"},
            "label": {"match": match},
            "cohorts": [group],
        }
        if reference and match and group != "EXACT_DUPLICATE":
            row.update(derived_from_asset_id=Path(reference).stem, transformation_id=group)
        items.append(row)

    for source in range(source_count):
        image = _procedural_art(seed + source * 97)
        reference = f"images/source-{source:03}.png"
        image.save(output / reference)
        references.append(reference)
        lineage = f"procedural-lineage-{seed}-{source}"
        asset(reference, lineage=lineage, group="REFERENCE", match=True)
        for group in TRANSFORM_GROUPS:
            query = (
                reference
                if group == "EXACT_DUPLICATE"
                else (f"images/source-{source:03}-{group.lower()}.png")
            )
            transformed, region = _transform(image, group)
            if group != "EXACT_DUPLICATE":
                transformed.save(output / query)
            asset(query, lineage=lineage, group=group, match=True, reference=reference)
            cases.append(
                {
                    "id": f"source-{source:03}-{group}",
                    "query": query,
                    "reference": reference,
                    "label": True,
                    "group": group,
                    "source_lineage_id": lineage,
                    "ground_truth_query_bbox": region,
                }
            )
        for ordinal, group in enumerate(NEGATIVE_GROUPS):
            query = f"images/source-{source:03}-{group.lower()}.png"
            _procedural_art(
                seed + 100_000 + source * 991 + ordinal * 137, composition=ordinal + 1
            ).save(output / query)
            negative_lineage = f"independent-{seed}-{source}-{ordinal}"
            asset(query, lineage=negative_lineage, group=group, match=False)
            cases.append(
                {
                    "id": f"source-{source:03}-{group}",
                    "query": query,
                    "reference": reference,
                    "label": False,
                    "group": group,
                    "source_lineage_id": negative_lineage,
                }
            )

    ai_status = {
        "state": "UNAVAILABLE",
        "reason_code": "NO_AUTHORIZED_GENERATOR_FIXTURES",
        "cases": 0,
        "generation_model": None,
    }
    if authorized_ai_fixtures is not None:
        supplied = json.loads(authorized_ai_fixtures.read_text(encoding="utf-8"))
        ai_cases = supplied.get("cases")
        if not isinstance(ai_cases, list) or not ai_cases:
            raise ValueError("Authorized AI fixture manifest requires a nonempty cases list")
        for index, entry in enumerate(ai_cases):
            rights = entry.get("rights") or {}
            if rights.get("state") not in {
                "OWNED",
                "AUTHORIZED",
                "LICENSED",
                "PUBLIC_DOMAIN_VERIFIED",
            } or not rights.get("reference"):
                raise ValueError("AI fixtures require explicit authorization/reference")
            if (
                not entry.get("model")
                or not entry.get("generation_record")
                or not isinstance(entry.get("copy_label"), bool)
            ):
                raise ValueError(
                    "AI fixtures require model, generation_record and boolean copy_label"
                )
            target_paths = {}
            for kind in ("reference", "query"):
                source = _safe_fixture_path(
                    authorized_ai_fixtures.resolve().parent, str(entry[kind])
                )
                with Image.open(source) as opened:
                    opened.verify()
                location = f"images/authorized-ai-{index:03}-{kind}{source.suffix.lower()}"
                shutil.copyfile(source, output / location)
                target_paths[kind] = location
                asset(
                    location,
                    lineage=f"authorized-ai-lineage-{index}",
                    group="AI_IMAGE_TO_IMAGE",
                    match=entry["copy_label"],
                    rights=rights,
                )
            references.append(target_paths["reference"])
            cases.append(
                {
                    "id": f"authorized-ai-{index:03}",
                    **target_paths,
                    "label": entry["copy_label"],
                    "group": "AI_IMAGE_TO_IMAGE",
                    "source_lineage_id": f"authorized-ai-lineage-{index}",
                    "generator_model": entry["model"],
                    "generation_record": entry["generation_record"],
                }
            )
        ai_status = {
            "state": "SUPPLIED_AUTHORIZED_FIXTURES",
            "cases": len(ai_cases),
            "reason_code": None,
            "generation_model": "PER_CASE_MANIFEST",
        }

    # These label deterministic permission/coverage outcomes independently of
    # detector accuracy. Fixture authorization is confined to this benchmark DB.
    for case_id, intended_use, catalog, expected_policy, abstention in (
        ("policy-licensed", "marketing/social", "benchmark-catalog", "PASS_BY_POLICY", None),
        ("policy-unlicensed-use", "commercial/unlicensed", "benchmark-catalog", "REVIEW", None),
        ("scope-empty", "marketing/social", "empty-catalog", "REVIEW", True),
    ):
        cases.append(
            {
                "id": case_id,
                "query": references[0],
                "reference": references[0],
                "label": catalog != "empty-catalog",
                "group": "POLICY_AND_COVERAGE",
                "source_lineage_id": f"procedural-lineage-{seed}-0",
                "catalog_id": catalog,
                "intended_use": intended_use,
                "expected_policy": expected_policy,
                "expected_abstention": abstention,
                "copy_metrics_eligible": False,
            }
        )
    corpus = {
        "schema": "creatorproof.corpus_manifest.v1",
        "manifest_id": f"phase1-procedural-{seed}-v1",
        "dataset_id": "phase1-internal-procedural-v1",
        "lane": "COPY",
        "partition": "DEMO",
        "domain_id": "INTERNAL_PROCEDURAL_ART",
        "items": items,
        "limitations": [
            "Procedural smoke fixtures, not a held-out real-world accuracy corpus.",
            "Creator and style negative cohorts are artificial proxies.",
            "Procedural synthesis is not evidence of AI-generator origin.",
        ],
    }
    _write_json(output / "corpus.json", corpus)
    load_corpus_manifest(output / "corpus.json")
    manifest = {
        "schema": "creatorproof.phase1_benchmark_manifest.v1",
        "seed": seed,
        "corpus_manifest_paths": ["corpus.json"],
        "references": references,
        "cases": cases,
        "ai_image_to_image": ai_status,
        "limitations": corpus["limitations"],
    }
    _write_json(output / "benchmark.json", manifest)
    return output / "benchmark.json"


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize(records: list[dict]) -> dict:
    copy_rows = [row for row in records if row.get("copy_metrics_eligible", True)]
    tp = sum(row["label"] and row["predicted_match"] for row in copy_rows)
    fn = sum(row["label"] and not row["predicted_match"] for row in copy_rows)
    fp = sum(not row["label"] and row["predicted_match"] for row in copy_rows)
    tn = sum(not row["label"] and not row["predicted_match"] for row in copy_rows)
    latency = sorted(row["latency_ms"] for row in records)
    localization = [row for row in copy_rows if row.get("localization_success") is not None]
    policy = [row for row in records if row.get("expected_policy") is not None]
    abstention = [row for row in records if row.get("expected_abstention") is not None]
    review_rows = [row for row in copy_rows if row.get("review_threshold_positive")]
    positive_rows = [row for row in copy_rows if row["label"]]
    fpr = _rate(fp, fp + tn)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "true_negative": tn,
        "false_negative": fn,
        "precision": _rate(tp, tp + fp),
        "recall": _rate(tp, tp + fn),
        "retrieval_recall": _rate(
            sum(row["reference_retrieved"] for row in positive_rows), len(positive_rows)
        ),
        "false_positive_rate": fpr,
        "false_negative_rate": _rate(fn, tp + fn),
        "precision_at_review_threshold": _rate(
            sum(row["label"] for row in review_rows), len(review_rows)
        ),
        "recall_at_observed_fp_burden_below_1_per_1000": _rate(tp, tp + fn)
        if fpr is not None and fpr <= 0.001
        else None,
        "false_positive_burden_per_1000_negative_scans": fpr * 1000 if fpr is not None else None,
        "acceptable_false_positive_burden_established": False,
        "localization_success_rate": _rate(
            sum(row["localization_success"] for row in localization), len(localization)
        ),
        "localization_case_count": len(localization),
        "pixel_segmentation_iou": None,
        "geometry_validation_rate": _rate(
            sum(row["geometry_validated"] for row in positive_rows), len(positive_rows)
        ),
        "abstention_rate": _rate(sum(row["abstention"] for row in records), len(records)),
        "correctly_abstained_rate": _rate(
            sum(row["abstention"] == row["expected_abstention"] for row in abstention),
            len(abstention),
        ),
        "correctly_abstained_labeled_cases": len(abstention),
        "median_latency_ms": median(latency) if latency else None,
        "p95_latency_ms": latency[max(0, int(len(latency) * 0.95 + 0.999) - 1)]
        if latency
        else None,
        "review_time_ms": None,
        "human_override_rate": None,
        "complete_evidence_packet_rate": _rate(
            sum(row["evidence_complete"] for row in records), len(records)
        ),
        "policy_decision_accuracy": _rate(
            sum(row["policy_action"] == row["expected_policy"] for row in policy), len(policy)
        ),
        "policy_labeled_cases": len(policy),
        "review_rate": _rate(
            sum(row["policy_action"] == "REVIEW" for row in records), len(records)
        ),
    }


def _localized(match: dict, bbox: list[float] | None) -> bool | None:
    if bbox is None:
        return None
    geometry = match.get("geometry") or {}
    if not geometry.get("validated") and not match.get("exact_sha256"):
        return False
    regions = (match.get("visualization") or {}).get("regions") or []
    centers = []
    for region in regions:
        polygon = region.get("query_polygon") or []
        if polygon:
            centers.append(
                (
                    sum(point[0] for point in polygon) / len(polygon),
                    sum(point[1] for point in polygon) / len(polygon),
                )
            )
    return bool(centers) and all(
        bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3] for x, y in centers
    )


def run_benchmark(
    manifest_path: Path, *, local_sscd_model: Path | None = None, max_cases: int | None = None
) -> dict:
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    manifest_path = manifest_path.resolve()
    root = manifest_path.parent
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = payload.get("cases") or []
    if max_cases is not None:
        cases = cases[:max_cases]
    if not cases:
        raise ValueError("Benchmark requires at least one case")
    corpus = bind_benchmark_input_to_corpus(
        benchmark_manifest_path=manifest_path,
        benchmark_payload=payload,
        lane="COPY",
        referenced_locations=[str(case[key]) for case in cases for key in ("query", "reference")],
        required_partition="DEMO",
    )
    for item in load_corpus_manifest(root / "corpus.json").items:
        path = _safe_fixture_path(root, item.location)
        if hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256:
            raise ValueError(f"Fixture hash mismatch: {item.location}")
    runtime = root / f"run-{time.time_ns()}"
    runtime.mkdir()
    settings = Settings(
        _env_file=None,
        environment="test",
        database_url=f"sqlite:///{runtime / 'benchmark.db'}",
        storage_root=runtime / "objects",
        proof_log_path=runtime / "proof.jsonl",
        job_backend="inline",
        storage_provider="local",
        dev_auth_enabled=True,
        dev_api_key="internal-benchmark-fixture-key",
        rate_limit_requests_per_minute=100_000,
        rate_limit_burst=10_000,
        model_bundle_path=API_ROOT / "model_lab/bundles/creatorproof-runtime-ready-v1.json",
        runtime_lock_path=API_ROOT / "uv.lock",
        statement_signing_private_key_hex="",
        trusted_issuer_key_sha256="",
        bootstrap_api_key="",
        sscd_model_path=local_sscd_model or runtime / "sscd-not-configured.pt",
        sscd_provider="local",
        sscd_device="cpu",
        sscd_remote_url="",
        style_remote_url="",
        synthetic_detector="off",
        c2pa_mode="off",
        visible_ai_marker_mode="off",
        style_provider="diagnostic",
        proof_anchor_mode="none",
        synthetic_policy_mode="INFORMATIONAL",
        copy_retrieval_requirement="BASELINE_ALLOWED",
        unsplash_access_key="",
        pixabay_api_key="",
        aiand_api_key="",
        sightengine_api_secret="",
    )
    app = create_app(settings)
    records = []
    with TestClient(app) as client:
        container = app.state.container
        headers = {"X-API-Key": settings.dev_api_key}
        reference_ids = {}
        for reference in payload["references"]:
            path = _safe_fixture_path(root, reference)
            response = client.post(
                "/v1/works",
                headers=headers,
                data={
                    "title": f"Internal procedural fixture: {path.stem}",
                    "catalog_id": "benchmark-catalog",
                    "rights_path": "EXISTING_LICENSE",
                    "allowed_uses": json.dumps(["marketing/social"]),
                    "claimant": "Internal authorized benchmark fixture",
                    "claim_state": "CORROBORATED",
                },
                files={
                    "file": (
                        path.name,
                        path.read_bytes(),
                        mimetypes.guess_type(path.name)[0] or "image/png",
                    )
                },
            )
            if response.status_code != 201:
                raise RuntimeError(f"Registration failed with HTTP {response.status_code}")
            reference_ids[reference] = response.json()["id"]
        for case in cases:
            path = _safe_fixture_path(root, case["query"])
            start = time.perf_counter()
            response = client.post(
                "/v1/scans",
                headers={**headers, "Idempotency-Key": case["id"]},
                data={
                    "catalog_id": case.get("catalog_id", "benchmark-catalog"),
                    "intended_use": case.get("intended_use", "marketing/social"),
                },
                files={
                    "file": (
                        path.name,
                        path.read_bytes(),
                        mimetypes.guess_type(path.name)[0] or "image/png",
                    )
                },
            )
            elapsed = (time.perf_counter() - start) * 1000
            if response.status_code != 202:
                raise RuntimeError(f"Scan {case['id']} failed with HTTP {response.status_code}")
            scan = response.json()
            packet = scan.get("evidence_packet") or {}
            matrix_response = client.get(f"/v1/scans/{scan['id']}/evidence-matrix", headers=headers)
            matrix = matrix_response.json() if matrix_response.status_code == 200 else {}
            matches = packet.get("matches") or []
            expected_id = reference_ids[case["reference"]]
            correct_matches = [match for match in matches if match.get("work_id") == expected_id]
            top = correct_matches[0] if correct_matches else {}
            required = {
                "candidate_commitment",
                "scope",
                "matches",
                "synthetic_origin",
                "provenance",
                "decision",
                "proof",
                "model_bundle",
                "limitations",
            }
            lanes = {signal.get("lane") for signal in matrix.get("signals", [])}
            records.append(
                {
                    "case": case["id"],
                    "asset_id": Path(case["query"]).stem,
                    "source_lineage_id": case["source_lineage_id"],
                    "cohorts": [case["group"]],
                    "label": case["label"],
                    "predicted_match": scan.get("match_status") == "MATCH_FOUND",
                    "reference_retrieved": bool(correct_matches),
                    "match_status": scan.get("match_status"),
                    "policy_action": scan.get("policy_action"),
                    "expected_policy": case.get("expected_policy"),
                    "expected_abstention": case.get("expected_abstention"),
                    "copy_metrics_eligible": case.get("copy_metrics_eligible", True),
                    "review_threshold_positive": scan.get("match_status")
                    in {"MATCH_FOUND", "INCONCLUSIVE"},
                    "geometry_validated": bool((top.get("geometry") or {}).get("validated")),
                    "localization_success": _localized(top, case.get("ground_truth_query_bbox")),
                    "abstention": bool(matrix.get("abstention")),
                    "latency_ms": round(elapsed, 3),
                    "evidence_complete": bool(
                        required <= packet.keys()
                        and matrix.get("persisted")
                        and MATRIX_LANES <= lanes
                    ),
                    "evidence_packet_hash": (packet.get("proof") or {}).get("packet_hash_sha256"),
                    "matrix_status": matrix.get("final_status"),
                    "reason_codes": scan.get("reason_codes", []),
                }
            )
        availability = {
            "copy_retrieval_sscd": bool(container.ai_retrieval.available),
            "copy_geometry": True,
            "copy_aligned_perceptual": True,
            "ai_origin": False,
            "provenance": False,
            "creator_profile": False,
            "ai_image_to_image": payload["ai_image_to_image"],
        }
        identity = benchmark_run_identity(
            lane="COPY",
            manifest_payload=payload,
            model_bundle=container.model_bundle,
            threshold_policy_id="creatorproof-copy-fusion-operating-points-v3",
            corpus_manifest_set_digest_sha256=corpus["manifest_set_digest_sha256"],
        )
        runtime_identity = {
            "application_revision": container.model_bundle_runtime.get("application_revision"),
            "qualification_state": container.model_bundle.qualification_state,
            "demo_ready": container.model_bundle_runtime.get("demo_ready"),
        }
    metrics = summarize(records)
    report = {
        "schema": "creatorproof.copy_benchmark.v2",
        "phase1_contract": "creatorproof.phase1_benchmark.v1",
        "run_identity": identity,
        "corpus_integrity": corpus,
        "records": records,
        "evaluation_grade": "SMOKE_TEST_ONLY",
        "evaluation_eligible": False,
        "promotion_eligible": False,
        "promotion_decision": {
            "state": "NOT_EVALUATED",
            "reason_code": "INTERNAL_PROCEDURAL_SMOKE_CORPUS",
            "acceptance_policy_digest_sha256": None,
        },
        "minimum_support_gate": {
            "held_out_lineages": 10,
            "positive_pairs": 20,
            "hard_negative_pairs": 20,
        },
        "operating_configuration": {
            "mode": "LOCAL_SSCD" if local_sscd_model else "OFFLINE_BASELINE",
            "network_calls": False,
            "thresholds_changed": False,
            "max_cases": max_cases,
            "latency_scope": "IN_PROCESS_API_END_TO_END",
        },
        "provider_availability": availability,
        "observed_runtime_identity": runtime_identity,
        "metrics": metrics,
        "transform_groups": dict(Counter(row["cohorts"][0] for row in records)),
        "unmeasured": {
            "review_time_ms": "No timed human review session was performed.",
            "human_override_rate": "No human review dispositions were sampled.",
            "pixel_segmentation_iou": "Verified support envelopes are not segmentation masks.",
            "real_world_accuracy": "Procedural internal fixtures cannot establish field accuracy.",
        },
        "warning": (
            "Internal procedural smoke benchmark only; no model promotion or legal accuracy claim."
        ),
        "limitations": payload["limitations"]
        + [
            "No network providers are invoked; origin/provenance/profile availability is false.",
            "Localization scores only known partial-reuse/screenshot support-envelope centers.",
            "Observed zero false positives cannot establish a 1-per-1000 population burden.",
        ],
    }
    report = seal_benchmark_report(report)
    validate_benchmark_report_payload(report)
    _write_json(root / "report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--sources", type=int, default=4)
    generate.add_argument("--seed", type=int, default=731)
    generate.add_argument("--authorized-ai-fixtures", type=Path)
    run = commands.add_parser("run")
    run.add_argument("manifest", type=Path)
    run.add_argument("--local-sscd-model", type=Path)
    run.add_argument("--max-cases", type=int)
    args = parser.parse_args()
    if args.command == "generate":
        print(
            generate_dataset(
                args.output,
                source_count=args.sources,
                seed=args.seed,
                authorized_ai_fixtures=args.authorized_ai_fixtures,
            )
        )
    else:
        report = run_benchmark(
            args.manifest, local_sscd_model=args.local_sscd_model, max_cases=args.max_cases
        )
        print(
            json.dumps(
                {
                    "report": str(args.manifest.resolve().parent / "report.json"),
                    "metrics": report["metrics"],
                    "report_digest_sha256": report["report_digest_sha256"],
                },
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
