"""Measure the copy lane against a battery of real-world reuse transforms.

The pipeline is easy to reason about in the abstract and hard to reason about at
its edges, which is where it actually gets used: a reposted image has been
cropped, rescaled, recompressed and had a caption stapled to it before anyone
scans it. This harness drives the same three stages a scan drives — geometry,
aligned perceptual, fusion — over a fixed set of transforms so a threshold
change can be judged on recall and false positives rather than on one example.

Two families of case are generated for every reference image:

  * positives, which are derived from the reference and *must* be caught;
  * negatives, which are different images and must never be called a match.

A change that lifts recall while moving a single negative into MATCH is a
regression, so both numbers are always reported together.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.container import build_container  # noqa: E402
from app.core.config import Settings  # noqa: E402
from app.services.copy_fusion import fuse_copy_evidence  # noqa: E402

Transform = Callable[[Image.Image], Image.Image]


def _jpeg(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    out = Image.open(buffer)
    out.load()
    return out.convert("RGB")


def _crop(image: Image.Image, fraction: float) -> Image.Image:
    width, height = image.size
    dx = int(width * (1 - fraction) / 2)
    dy = int(height * (1 - fraction) / 2)
    return image.crop((dx, dy, width - dx, height - dy))


def _scale(image: Image.Image, factor: float) -> Image.Image:
    return image.resize(
        (max(1, int(image.width * factor)), max(1, int(image.height * factor))),
        Image.LANCZOS,
    )


def _caption(image: Image.Image) -> Image.Image:
    """A repost with a caption bar stapled across the bottom."""
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    bar = max(24, out.height // 8)
    draw.rectangle((0, out.height - bar, out.width, out.height), fill=(12, 12, 14))
    draw.text((10, out.height - bar + 6), "REPOSTED  @someone", fill=(245, 245, 245))
    return out


def _letterbox(image: Image.Image) -> Image.Image:
    """Padded into a 16:9 frame, the way a video thumbnail would carry it."""
    target_w = image.width
    target_h = max(1, int(image.width * 9 / 16))
    if target_h < image.height:
        target_h = image.height
        target_w = max(1, int(image.height * 16 / 9))
    canvas = Image.new("RGB", (target_w, target_h), (0, 0, 0))
    canvas.paste(image.convert("RGB"), ((target_w - image.width) // 2, (target_h - image.height) // 2))
    return canvas


def _screenshot(image: Image.Image) -> Image.Image:
    """Screenshotted then re-saved: slight scale, chrome bar, heavy recompression."""
    scaled = _scale(image, 0.82).convert("RGB")
    bar = max(18, scaled.height // 14)
    canvas = Image.new("RGB", (scaled.width, scaled.height + bar), (238, 238, 240))
    canvas.paste(scaled, (0, bar))
    draw = ImageDraw.Draw(canvas)
    draw.ellipse((6, bar // 2 - 4, 14, bar // 2 + 4), fill=(255, 95, 86))
    return _jpeg(canvas, 68)


def _social_repost(image: Image.Image) -> Image.Image:
    """The common real case: crop, downscale, saturate, recompress twice."""
    step = _crop(image, 0.86)
    step = _scale(step, 0.7)
    step = ImageEnhance.Color(step.convert("RGB")).enhance(1.18)
    step = _jpeg(step, 74)
    return _jpeg(step, 82)


# Some images in the sample pool are genuinely the same work, or two renders of
# one generated scene. Counting a flag on those as a false positive would push
# the thresholds to hide correct behaviour, so they are scored separately.
RELATED_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"img01.png", "img12.png"}),  # the same ink illustration
    frozenset({"img02.png", "img06.png"}),  # one generated scene, two renders
)


def _related(left: str, right: str) -> bool:
    return any({left, right} <= group for group in RELATED_GROUPS)


POSITIVES: dict[str, Transform] = {
    "identical_reencode": lambda im: _jpeg(im, 95),
    "jpeg_q80": lambda im: _jpeg(im, 80),
    "jpeg_q55": lambda im: _jpeg(im, 55),
    "jpeg_q35": lambda im: _jpeg(im, 35),
    "scale_50pct": lambda im: _scale(im, 0.5),
    "scale_30pct": lambda im: _scale(im, 0.3),
    "scale_150pct": lambda im: _scale(im, 1.5),
    "crop_90pct": lambda im: _crop(im, 0.90),
    "crop_75pct": lambda im: _crop(im, 0.75),
    "crop_60pct": lambda im: _crop(im, 0.60),
    "crop_45pct": lambda im: _crop(im, 0.45),
    "rotate_2deg": lambda im: im.rotate(2, expand=True, resample=Image.BICUBIC),
    "rotate_10deg": lambda im: im.rotate(10, expand=True, resample=Image.BICUBIC),
    "rotate_90deg": lambda im: im.rotate(90, expand=True),
    "hflip": lambda im: im.transpose(Image.FLIP_LEFT_RIGHT),
    "brightness_125": lambda im: ImageEnhance.Brightness(im.convert("RGB")).enhance(1.25),
    "contrast_80": lambda im: ImageEnhance.Contrast(im.convert("RGB")).enhance(0.8),
    "grayscale": lambda im: im.convert("L").convert("RGB"),
    "saturate_160": lambda im: ImageEnhance.Color(im.convert("RGB")).enhance(1.6),
    "blur_soft": lambda im: im.convert("RGB").filter(ImageFilter.GaussianBlur(1.2)),
    "caption_bar": _caption,
    "letterbox": _letterbox,
    "screenshot": _screenshot,
    "social_repost": _social_repost,
    "crop_then_jpeg": lambda im: _jpeg(_crop(im, 0.7), 60),
    "scale_then_rotate": lambda im: _scale(im, 0.6).rotate(5, expand=True, resample=Image.BICUBIC),
}


def _phash_similarity(container, left: bytes, right: bytes, left_img, right_img) -> float:
    a = container.fingerprints.compute(left, left_img)
    b = container.fingerprints.compute(right, right_img)
    try:
        import imagehash

        distance = imagehash.hex_to_hash(a.phash) - imagehash.hex_to_hash(b.phash)
    except Exception:
        return 0.0
    return max(0.0, 1.0 - distance / 64.0)


def _encode(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def evaluate(container, settings, query: Image.Image, reference: Image.Image) -> dict:
    """Run the copy lane over one pair, returning what the scan would record."""
    embedder = container.ai_retrieval
    ai_similarity = None
    if getattr(embedder, "available", False):
        try:
            ai_similarity = embedder.similarity(embedder.embed(query), embedder.embed(reference))
        except Exception:
            ai_similarity = None

    # Same gate the scan applies, so the benchmark measures the shipped policy
    # rather than a more generous one.
    escalate = (
        ai_similarity is not None
        and ai_similarity >= settings.copy_alignment_escalation_similarity
    )
    raw_geometry = asdict(container.geometry.verify(query, reference, escalate=escalate))
    alignment = (
        raw_geometry.get("homography_query_to_reference")
        if raw_geometry.get("alignment_grade") in {"STRICT", "CORROBORATION_REQUIRED"}
        else None
    )
    aligned = asdict(
        container.aligned_perceptual.verify(
            query,
            reference,
            alignment,
            raw_geometry.get("regions") if alignment is not None else None,
        )
    )
    geometry = {
        key: value
        for key, value in raw_geometry.items()
        if key
        not in {"query_size", "reference_size", "correspondences", "regions", "homography_query_to_reference"}
    }

    phash = _phash_similarity(container, _encode(query), _encode(reference), query, reference)
    fusion = asdict(
        fuse_copy_evidence(
            exact_sha256=False,
            ai_similarity=ai_similarity,
            phash_similarity=phash,
            geometry=geometry,
            aligned_perceptual=aligned,
            settings=settings,
        )
    )
    return {
        "match": bool(fusion["match_supported"]),
        "review": bool(fusion["review_supported"]),
        "index": round(float(fusion["evidence_index"]), 4),
        "tier": fusion["evidence_tier"],
        "classification": fusion["classification"],
        "geometry_valid": bool(geometry.get("validated")),
        "geometry_reasons": geometry.get("rejection_reasons") or [],
        "inliers": geometry.get("inliers"),
        "tentative": geometry.get("tentative_matches"),
        "inlier_ratio": round(float(geometry.get("inlier_ratio") or 0.0), 4),
        "sym_error": geometry.get("symmetric_transfer_error_normalized"),
        "q_cov": round(float(geometry.get("query_coverage") or 0.0), 4),
        "r_cov": round(float(geometry.get("reference_coverage") or 0.0), 4),
        "aligned": bool(aligned.get("available")),
        "aligned_reason": aligned.get("reason"),
        "reflected": bool(raw_geometry.get("reflected")),
        "grade": raw_geometry.get("alignment_grade"),
        "structure": aligned.get("structure_consensus"),
        "overlap": aligned.get("overlap_ratio"),
        "ai": None if ai_similarity is None else round(ai_similarity, 4),
        "phash": round(phash, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refs", default="/tmp/bench/refs", help="Directory of reference images")
    parser.add_argument("--out", default="/tmp/bench/results.json")
    parser.add_argument("--only", default="", help="Comma-separated transform names to run")
    parser.add_argument("--negatives", action="store_true", help="Also run cross-image negatives")
    args = parser.parse_args()

    settings = Settings(
        environment="test",
        database_url="sqlite:///:memory:",
        storage_root=Path("/tmp/bench/objects"),
        job_backend="inline",
        proof_log_path=Path("/tmp/bench/proof-log.jsonl"),
        proof_anchor_mode="none",
        style_provider="diagnostic",
        synthetic_detector="off",
        c2pa_mode="off",
        visible_ai_marker_mode="off",
        copy_retrieval_requirement="BASELINE_ALLOWED",
    )
    container = build_container(settings)
    print(
        f"embedding provider: {container.ai_retrieval.name} "
        f"available={getattr(container.ai_retrieval, 'available', False)}",
        file=sys.stderr,
    )

    refs = sorted(Path(args.refs).glob("*.png"))
    if not refs:
        print(f"no reference images in {args.refs}", file=sys.stderr)
        return 1

    selected = [name.strip() for name in args.only.split(",") if name.strip()]
    transforms = {k: v for k, v in POSITIVES.items() if not selected or k in selected}

    rows: list[dict] = []
    images = {path.name: Image.open(path).convert("RGB") for path in refs}

    for name, reference in images.items():
        for label, transform in transforms.items():
            try:
                query = transform(reference)
            except Exception as exc:  # a transform that cannot run is not a detector failure
                rows.append({"ref": name, "case": label, "kind": "positive", "error": str(exc)})
                continue
            result = evaluate(container, settings, query, reference)
            rows.append({"ref": name, "case": label, "kind": "positive", **result})
            print(
                f"{name:14s} {label:20s} match={result['match']!s:5s} "
                f"idx={result['index']:.3f} geo={result['geometry_valid']!s:5s} "
                f"ai={result['ai']} struct={result['structure']} "
                f"{','.join(result['geometry_reasons'][:2])}",
                file=sys.stderr,
            )

    if args.negatives:
        # Two grades of negative. Whole-image pairs are the easy case; the
        # derived pairs put a transformed crop of one work against a different
        # work, which is what a threshold that has been loosened too far starts
        # calling a match.
        names = list(images)
        negative_pairs: list[tuple[str, str, Image.Image, str, Image.Image]] = []
        for i, left in enumerate(names):
            for right in names[i + 1 :]:
                negative_pairs.append((left, f"vs_{left}", images[left], right, images[right]))
        for i, left in enumerate(names):
            right = names[(i + 3) % len(names)]
            if left == right:
                continue
            negative_pairs.append(
                (left, f"hard_crop_vs_{left}", _crop(_jpeg(images[left], 70), 0.7), right, images[right])
            )
            negative_pairs.append(
                (left, f"hard_scale_vs_{left}", _scale(images[left], 0.55), right, images[right])
            )

        for source, case, query, right, reference in negative_pairs:
            result = evaluate(container, settings, query, reference)
            kind = "related" if _related(source, right) else "negative"
            rows.append({"ref": right, "case": case, "kind": kind, **result})
            if result["match"] or result["review"]:
                print(
                    f"{kind.upper():8s}-FLAG {case:26s}/{right:12s} match={result['match']!s:5s} "
                    f"review={result['review']!s:5s} idx={result['index']:.3f} ai={result['ai']}",
                    file=sys.stderr,
                )

    positives = [r for r in rows if r.get("kind") == "positive" and "error" not in r]
    negatives = [r for r in rows if r.get("kind") == "negative"]
    related = [r for r in rows if r.get("kind") == "related"]
    caught = [r for r in positives if r["match"]]
    reviewed = [r for r in positives if not r["match"] and r["review"]]
    missed = [r for r in positives if not r["match"] and not r["review"]]

    summary = {
        "positives": len(positives),
        "match": len(caught),
        "review_only": len(reviewed),
        "missed": len(missed),
        "recall_match": round(len(caught) / max(1, len(positives)), 4),
        "recall_any": round((len(caught) + len(reviewed)) / max(1, len(positives)), 4),
        "mirror_recovered": sum(1 for r in positives if r.get("reflected")),
        "negatives": len(negatives),
        "false_match": sum(1 for r in negatives if r["match"]),
        "false_review": sum(1 for r in negatives if r["review"]),
        "related_pairs": len(related),
        "related_flagged": sum(1 for r in related if r["match"] or r["review"]),
    }

    by_case: dict[str, dict] = {}
    for row in positives:
        entry = by_case.setdefault(row["case"], {"n": 0, "match": 0, "review": 0, "missed": 0})
        entry["n"] += 1
        if row["match"]:
            entry["match"] += 1
        elif row["review"]:
            entry["review"] += 1
        else:
            entry["missed"] += 1

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "by_case": by_case, "rows": rows}, indent=2))

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, indent=2))
    print("\n=== BY TRANSFORM (match/review/missed of n) ===")
    for case, entry in sorted(by_case.items(), key=lambda kv: (kv[1]["match"] / max(1, kv[1]["n"]))):
        flag = "  <-- WEAK" if entry["match"] < entry["n"] else ""
        print(
            f"{case:22s} {entry['match']:>2}/{entry['n']:<2} match  "
            f"{entry['review']:>2} review  {entry['missed']:>2} missed{flag}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
