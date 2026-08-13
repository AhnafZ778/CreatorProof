"""Temporary diagnostic: measure each stage of build_evidence_packet."""

from __future__ import annotations

import io
import os
import time
import uuid

os.environ.setdefault("CREATORPROOF_STYLE_ALLOW_LEGACY_PICKLE", "true")
os.environ.setdefault(
    "CREATORPROOF_STYLE_CSD_EXPECTED_SHA256",
    "40e92fad63a361b8136100cd234c42d401ef9b34ff1748234318929ebcc7e7a1",
)

from PIL import Image

from app.container import build_container, initialize_database
from app.core.config import Settings
from app.services.images import decode_image


def _flush(msg: str) -> None:
    ts = time.strftime("%H:%M:%S", time.localtime())
    print(f"[{ts}] {msg}", flush=True)


def main() -> int:
    t_total_start = time.perf_counter()
    _flush("=== STALL DIAGNOSTIC START ===")

    _flush("Building container...")
    t0 = time.perf_counter()
    settings = Settings()
    container = build_container(settings)
    initialize_database(container)
    _flush(f"Container built in {(time.perf_counter() - t0) * 1000:.0f}ms")
    _flush(f"Job backend: {settings.job_backend}")

    # Count views
    from app.services.synthetic_analysis import _delivery_views, _spatial_views

    test_img = Image.new("RGB", (512, 512), (120, 80, 200))
    dv = _delivery_views(test_img)
    sv = _spatial_views(test_img, settings.synthetic_spatial_crop_fraction)
    total_views = len(dv) + len(sv)
    _flush(f"Delivery views: {len(dv)}, spatial views: {len(sv)}, total: {total_views}")
    _flush(f"Active detectors: {[d.name for d in container.synthetic_detection.detectors]}")
    _flush(
        f"Total detector×view calls: {len(container.synthetic_detection.detectors) * total_views}"
    )

    # Show OCR info
    _flush(f"OCR available: {container.visible_markers.available}")
    _flush(f"OCR timeout: {container.visible_markers.timeout_seconds}s")
    from app.providers.visible_markers import _views as ocr_views

    ocr_v = ocr_views(test_img)
    _flush(f"OCR views: {len(ocr_v)}, PSM modes: 2, total OCR subprocess calls: {len(ocr_v) * 2}")

    # External detector info
    for d in container.synthetic_detection.detectors:
        if hasattr(d, "timeout"):
            _flush(f"External detector '{d.name}' timeout={d.timeout}s")

    # Register a tiny work for copy-retrieval test
    db = container.database.session_factory()
    tenant_id = settings.dev_tenant_id

    img_bytes_buf = io.BytesIO()
    test_img.save(img_bytes_buf, format="PNG")
    img_bytes = img_bytes_buf.getvalue()

    _flush("\n--- R0: MEASURE EACH STAGE INDIVIDUALLY ---")

    # Stage: Image decode
    t0 = time.perf_counter()
    query_image = decode_image(
        img_bytes, max_bytes=settings.max_upload_bytes, max_pixels=settings.max_image_pixels
    )
    _flush(f"  Image decode: {(time.perf_counter() - t0) * 1000:.1f}ms")

    # Stage: Fingerprints
    t0 = time.perf_counter()
    fps = container.fingerprints.compute(img_bytes, query_image)
    _flush(f"  Fingerprints: {(time.perf_counter() - t0) * 1000:.1f}ms")

    # Stage: Provenance
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tf.write(img_bytes)
        tmp_path = Path(tf.name)
    t0 = time.perf_counter()
    provenance = container.provenance.inspect(tmp_path)
    _flush(f"  Provenance (C2PA): {(time.perf_counter() - t0) * 1000:.1f}ms")
    os.unlink(tmp_path)

    # Stage: Visible markers (OCR)
    t0 = time.perf_counter()
    from dataclasses import asdict

    try:
        visible_marker = asdict(container.visible_markers.inspect(query_image))
    except Exception:
        visible_marker = {"classification": "FAILED", "supports_ai_origin_review": False}
    _flush(f"  Visible markers (OCR): {(time.perf_counter() - t0) * 1000:.1f}ms")
    _flush(f"  Visible-marker result: {visible_marker['classification']}")

    # Stage: Synthetic analysis - Community Forensics ONLY (measure one view)
    cf_detector = None
    grip_detector = None
    for d in container.synthetic_detection.detectors:
        if d.name == "community-forensics-vit-small-384":
            cf_detector = d
        elif hasattr(d, "timeout"):
            grip_detector = d

    if cf_detector:
        _flush("  --- Community Forensics timing per view ---")
        for vname, vimg, _w, _s in dv[:2]:  # First 2 delivery views only
            t0 = time.perf_counter()
            cf_detector.predict(vimg)
            _flush(f"    CF {vname}: {(time.perf_counter() - t0) * 1000:.1f}ms")

    if grip_detector:
        _flush("  --- GRIP CLIPDet timing per view ---")
        for vname, vimg, _w, _s in dv[:2]:  # First 2 delivery views only
            t0 = time.perf_counter()
            grip_detector.predict(vimg)
            _flush(f"    GRIP {vname}: {(time.perf_counter() - t0) * 1000:.1f}ms")

    # Stage: Full synthetic analysis
    _flush("  --- Full synthetic analysis (all detectors, all views) ---")
    t0 = time.perf_counter()
    from app.services.synthetic_analysis import analyze_synthetic_origin

    synthetic_analysis = analyze_synthetic_origin(
        image=query_image,
        detector_router=container.synthetic_detection,
        provenance=provenance,
        settings=settings,
        visible_marker=visible_marker,
    )
    synth_dur = (time.perf_counter() - t0) * 1000
    _flush(f"  Full synthetic analysis: {synth_dur:.1f}ms ({synth_dur / 1000:.1f}s)")
    _flush(f"  Synthetic-origin result: {synthetic_analysis['classification']}")

    # Stage: Retrieval
    t0 = time.perf_counter()
    from app.services.retrieval import retrieve_candidates

    ranked, total_count, retrieval_runtime = retrieve_candidates(
        db,
        container=container,
        candidate_image=query_image,
        tenant_id=tenant_id,
        catalog_id="diag-empty",
        candidate_sha256=fps.sha256,
        candidate_phash=fps.phash,
        top_k=settings.retrieval_top_k,
    )
    _flush(f"  Retrieval: {(time.perf_counter() - t0) * 1000:.1f}ms (works found: {len(ranked)})")
    _flush(
        f"  Retrieval provider: {retrieval_runtime.provider}; eligible references: {total_count}"
    )

    # Stage: Style analysis
    t0 = time.perf_counter()
    from app.services.style_analysis import analyze_style

    try:
        style_analysis = analyze_style(
            container,
            db,
            query_image=query_image,
            tenant_id=tenant_id,
            catalog_id="diag-empty",
            top_k=settings.style_top_k,
        )
    except Exception as exc:
        style_analysis = {"error": str(exc)}
    style_dur = (time.perf_counter() - t0) * 1000
    _flush(f"  Style analysis: {style_dur:.1f}ms ({style_dur / 1000:.1f}s)")
    style_result = style_analysis.get("provider") or style_analysis.get("error", "unknown")
    _flush(f"  Style result: {style_result}")

    # Stage: Proof
    t0 = time.perf_counter()
    proof = container.proof_anchor.anchor("diagnostic_hash_" + uuid.uuid4().hex[:8])
    _flush(f"  Proof anchor: {(time.perf_counter() - t0) * 1000:.1f}ms")
    _flush(f"  Proof result: {proof.status}")

    total_ms = (time.perf_counter() - t_total_start) * 1000
    _flush(f"\n=== TOTAL DIAGNOSTIC TIME: {total_ms:.0f}ms ({total_ms / 1000:.1f}s) ===")

    # Compute worst-case budget
    external_count = sum(
        1 for d in container.synthetic_detection.detectors if hasattr(d, "timeout")
    )
    external_timeout = max(
        (d.timeout for d in container.synthetic_detection.detectors if hasattr(d, "timeout")),
        default=0,
    )
    _flush("\n--- WORST-CASE BUDGET ---")
    _flush(f"External detectors: {external_count}")
    _flush(f"External timeout per call: {external_timeout}s")
    _flush(f"Views per detector: {total_views}")
    _flush(f"GRIP calls worst case: {external_count * total_views}")
    _flush(f"GRIP worst-case budget: {external_count * total_views * external_timeout}s")
    ocr_call_count = len(ocr_v) * 2
    ocr_budget = ocr_call_count * container.visible_markers.timeout_seconds
    _flush(
        f"OCR worst-case: {ocr_call_count} subprocesses × "
        f"{container.visible_markers.timeout_seconds}s = {ocr_budget}s"
    )

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
