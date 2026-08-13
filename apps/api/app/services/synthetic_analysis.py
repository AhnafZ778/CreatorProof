from __future__ import annotations

import math
import time
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageFilter

from app.domain.enums import ProvenanceStatus


def _logit(value: float) -> float:
    clipped = min(max(float(value), 1e-5), 1.0 - 1e-5)
    return math.log(clipped / (1.0 - clipped))


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(float(value), 50.0), -50.0)))


def _jpeg(image: Image.Image, quality: int) -> Image.Image:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=False)
    buffer.seek(0)
    with Image.open(buffer) as opened:
        output = opened.convert("RGB")
        output.load()
    return output


def _delivery_views(image: Image.Image) -> list[tuple[str, Image.Image, float, str]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    scaled = rgb.resize(
        (max(64, round(width * 0.72)), max(64, round(height * 0.72))),
        Image.Resampling.BICUBIC,
    ).resize(rgb.size, Image.Resampling.BICUBIC)
    return [
        ("original", rgb, 1.0, "DELIVERY_TRANSFORM"),
        ("jpeg_95", _jpeg(rgb, 95), 0.92, "DELIVERY_TRANSFORM"),
        ("jpeg_75", _jpeg(rgb, 75), 0.76, "DELIVERY_TRANSFORM"),
        ("downscale_restore_72pct", scaled, 0.78, "DELIVERY_TRANSFORM"),
        (
            "gaussian_blur_0_55",
            rgb.filter(ImageFilter.GaussianBlur(0.55)),
            0.72,
            "DELIVERY_TRANSFORM",
        ),
    ]


def _spatial_views(
    image: Image.Image,
    fraction: float,
) -> list[tuple[str, Image.Image, float, str]]:
    """Return overlapping crops for localized generator-trace consensus.

    A crop can recover a signal lost when a large artwork is reduced to one model
    input. It may support a detector only when several spatially distinct crops
    agree; a single hot crop cannot decide the lane.
    """

    rgb = image.convert("RGB")
    width, height = rgb.size
    crop_width = max(64, min(width, round(width * fraction)))
    crop_height = max(64, min(height, round(height * fraction)))
    max_left = max(0, width - crop_width)
    max_top = max(0, height - crop_height)
    positions = {
        "center": (max_left // 2, max_top // 2),
        "top_left": (0, 0),
        "top_right": (max_left, 0),
        "bottom_left": (0, max_top),
        "bottom_right": (max_left, max_top),
    }
    output = []
    seen: set[tuple[int, int, int, int]] = set()
    for name, (left, top) in positions.items():
        box = (left, top, left + crop_width, top + crop_height)
        if box in seen:
            continue
        seen.add(box)
        output.append((f"crop_{name}", rgb.crop(box), 0.68, "SPATIAL_CROP"))
    return output


def _weighted_logit(scores: list[float], weights: list[float]) -> float:
    total = sum(weights)
    if total <= 0:
        return 0.5
    weighted = sum(weight * _logit(score) for score, weight in zip(scores, weights, strict=True))
    return _sigmoid(weighted / total)


def _spectral_diagnostics(image: Image.Image) -> dict:
    """Expose low-level traces without pretending they identify a generator."""
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32) / 255.0
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    spectrum = np.abs(np.fft.fftshift(np.fft.fft2(gray - float(gray.mean())))) ** 2
    yy, xx = np.indices(spectrum.shape)
    radius = np.sqrt((xx - width / 2.0) ** 2 + (yy - height / 2.0) ** 2)
    normalized_radius = radius / max(math.hypot(width / 2.0, height / 2.0), 1.0)
    total = float(spectrum.sum()) + 1e-12
    high_frequency_ratio = float(spectrum[normalized_radius >= 0.55].sum() / total)
    mid_frequency_ratio = float(
        spectrum[(normalized_radius >= 0.20) & (normalized_radius < 0.55)].sum() / total
    )
    laplacian = cv2.Laplacian(gray, cv2.CV_32F)
    residuals = rgb - cv2.GaussianBlur(rgb, (0, 0), 1.0)
    channels = residuals.reshape(-1, 3)
    off_diagonal: list[float] = []
    for first, second in ((0, 1), (0, 2), (1, 2)):
        left = channels[:, first] - float(channels[:, first].mean())
        right = channels[:, second] - float(channels[:, second].mean())
        denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
        off_diagonal.append(float(left @ right / denominator) if denominator > 1e-12 else 0.0)
    return {
        "high_frequency_energy_ratio": round(high_frequency_ratio, 6),
        "mid_frequency_energy_ratio": round(mid_frequency_ratio, 6),
        "laplacian_variance": round(float(laplacian.var()), 6),
        "residual_channel_correlation_mean": round(float(np.mean(off_diagonal)), 6),
        "semantics": "DESCRIPTIVE_FORENSIC_TRACES_NOT_AI_ORIGIN_PROOF",
    }


def _visible_marker_state(visible_marker: dict | None) -> tuple[bool, float, float | None]:
    marker = visible_marker or {}
    supported = bool(marker.get("supports_ai_origin_review"))
    strength = min(max(float(marker.get("marker_strength") or 0.0), 0.0), 1.0)
    markers = marker.get("markers") or []
    confidences = [
        min(max(float(item.get("ocr_confidence") or 0.0), 0.0), 1.0)
        for item in markers
        if isinstance(item, dict)
    ]
    return supported, strength, max(confidences) if confidences else None


def _origin_scorecard(
    *,
    fused_score: float | None,
    family_count: int,
    calibrated_family_count: int,
    minimum_families: int,
    review_threshold: float,
    transform_stability: float | None,
    negative_clearance_supported: bool,
    trusted_ai_assertion: bool,
    valid_untrusted_ai_assertion: bool,
    visible_marker: dict | None,
) -> dict:
    """Return signal strength and evidence quality as separate, non-probability readouts."""
    marker_supported, marker_strength, marker_confidence = _visible_marker_state(visible_marker)
    model_signal = round(100.0 * fused_score) if fused_score is not None else None
    marker_signal = round(100.0 * marker_strength) if marker_supported else None
    provenance_signal = (
        100 if trusted_ai_assertion else 82 if valid_untrusted_ai_assertion else None
    )
    available_signals = [
        float(value)
        for value in (model_signal, marker_signal, provenance_signal)
        if value is not None
    ]
    corroborating_sources = sum(
        (
            bool(fused_score is not None and fused_score >= review_threshold),
            marker_supported,
            trusted_ai_assertion or valid_untrusted_ai_assertion,
        )
    )
    signal_score = min(
        100,
        round(
            (max(available_signals) if available_signals else 0.0)
            + (5 if corroborating_sources >= 2 else 0)
        ),
    )

    coverage = min(family_count / max(minimum_families, 1), 1.0)
    calibration = calibrated_family_count / family_count if family_count else 0.0
    stability = min(max(float(transform_stability or 0.0), 0.0), 1.0)
    model_quality = round(100.0 * (0.35 * coverage + 0.35 * calibration + 0.30 * stability))
    marker_quality = (
        min(55, round(35.0 + 20.0 * float(marker_confidence or 0.0))) if marker_supported else 0
    )
    provenance_quality = 100 if trusted_ai_assertion else 55 if valid_untrusted_ai_assertion else 0
    quality_score = min(
        100,
        max(model_quality, marker_quality, provenance_quality)
        + (6 if corroborating_sources >= 2 else 0),
    )

    if signal_score >= 80:
        signal_label = "Strong AI signal"
    elif signal_score >= 58:
        signal_label = "AI signal found"
    elif signal_score >= 35:
        signal_label = "Weak AI signal"
    else:
        signal_label = "Little AI signal found"
    quality_label = "High" if quality_score >= 80 else "Medium" if quality_score >= 50 else "Low"

    marker_classification = (visible_marker or {}).get("classification")
    if marker_supported:
        marker_status = "Visible AI label found"
        marker_detail = "Useful for review, but visible labels can be copied, removed, or forged."
    elif marker_classification == "NO_VISIBLE_AI_MARKER_FOUND":
        marker_status = "No visible AI label found"
        marker_detail = "Neutral result — a missing label does not mean the image is human-made."
    else:
        marker_status = "Visible-label check unavailable"
        marker_detail = "No conclusion was drawn from this check."

    if trusted_ai_assertion:
        provenance_status = "Verified AI source information"
        provenance_detail = "Trusted signed source information identifies AI use."
    elif valid_untrusted_ai_assertion:
        provenance_status = "AI source claim not verified"
        provenance_detail = "An AI-use claim exists, but signer trust was not confirmed."
    else:
        provenance_status = "No verified source information"
        provenance_detail = (
            "Neutral result — missing source information does not prove human origin."
        )

    if family_count == 0:
        model_status = "AI model checks unavailable"
        model_detail = (
            "Activate at least two independent model families for a dependable quiet result."
        )
    elif negative_clearance_supported:
        model_status = "Model checks were quiet"
        model_detail = (
            "Independent, calibrated checks were quiet; this still does not prove human origin."
        )
    elif fused_score is not None and fused_score >= review_threshold:
        model_status = "AI model signal found"
        model_detail = (
            "The model signal is shown as strength, not as the chance that the image is AI-made."
        )
    else:
        model_status = "Model result is uncertain"
        model_detail = (
            "Coverage, calibration, stability, or agreement is not strong enough to clear origin."
        )

    return {
        "schema": "creatorproof.origin_scorecard.v1",
        "signal_score": signal_score,
        "signal_label": signal_label,
        "evidence_quality_score": quality_score,
        "evidence_quality_label": quality_label,
        "score_semantics": "SIGNAL_STRENGTH_AND_EVIDENCE_QUALITY_NOT_AI_PROBABILITY",
        "plain_explanation": (
            "AI signal measures how strongly the available checks reacted. Evidence quality "
            "measures how dependable those checks were. Neither number is a probability."
        ),
        "factors": [
            {
                "id": "model_checks",
                "label": "AI model checks",
                "signal_score": model_signal,
                "quality_score": model_quality if family_count else None,
                "status": model_status,
                "detail": model_detail,
                "neutral_when_missing": True,
            },
            {
                "id": "visible_label",
                "label": "Visible AI label",
                "signal_score": marker_signal,
                "quality_score": marker_quality if marker_supported else None,
                "status": marker_status,
                "detail": marker_detail,
                "neutral_when_missing": True,
            },
            {
                "id": "signed_source",
                "label": "Signed source information",
                "signal_score": provenance_signal,
                "quality_score": provenance_quality if provenance_quality else None,
                "status": provenance_status,
                "detail": provenance_detail,
                "neutral_when_missing": True,
            },
        ],
    }


def _presentation(
    *,
    classification: str,
    evidence_tier: str,
    family_count: int,
    calibrated_family_count: int,
    positive_family_count: int,
    transform_stability: float | None,
    provenance_status,
    ai_assertion: bool,
    trusted_ai_assertion: bool,
    show_domain_score: bool,
    fused_score: float | None,
    visible_marker_supported: bool,
) -> dict:
    if classification == "AI_PROVENANCE_CONFIRMED":
        state = "AI_CONFIRMED"
        headline = "Signed provenance identifies AI use"
        summary = "Trusted Content Credentials contain an AI-use assertion."
        action = "Review the separate copy and style lanes before making a rights decision."
    elif classification == "LIKELY_AI_GENERATED":
        state = "AI_INDICATORS_FOUND"
        headline = "Multiple checks found AI-generation indicators"
        summary = (
            f"{positive_family_count} independent evidence families agreed and the signal "
            "survived common delivery changes."
        )
        action = "Keep this case in review and inspect copy and creator-profile evidence next."
    elif classification == "AI_INDICATORS_CORROBORATED":
        state = "AI_INDICATORS_FOUND"
        headline = "AI indicators were found by more than one check"
        summary = (
            "A visible AI label and an AI model signal agree. This is strong review evidence, "
            "not proof of infringement."
        )
        action = (
            "Keep this image in review and check for protected-work or creator-profile resemblance."
        )
    elif classification == "AI_ORIGIN_MARKER_FOUND":
        state = "AI_INDICATORS_NEED_REVIEW"
        headline = "A visible AI label was found"
        summary = (
            "Text in the image explicitly identifies AI use. The label may be genuine, copied, "
            "or forged, so it is review evidence rather than proof."
        )
        action = (
            "Do not auto-clear this image; review the highlighted label and the other evidence "
            "lanes."
        )
    elif classification in {
        "AI_ORIGIN_REVIEW_CANDIDATE",
        "AI_PROVENANCE_ASSERTED_UNTRUSTED_SIGNER",
    }:
        state = "AI_INDICATORS_NEED_REVIEW"
        headline = "AI-generation indicators need review"
        summary = (
            "At least one check responded, but independent support, calibration, or signer trust "
            "is not strong enough for a confident origin finding."
        )
        action = "Do not auto-clear this image; add a complementary detector or verify provenance."
    elif classification == "NO_AI_ORIGIN_EVIDENCE_DETECTED":
        state = "NO_STRONG_AI_SIGNAL"
        headline = "No strong AI-generation indicators were found"
        summary = (
            "Multiple calibrated, independent checks were quiet in the recorded deployment domain. "
            "This does not prove human origin."
        )
        action = "Continue with copy and style checks; origin evidence alone cannot clear rights."
    elif classification == "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE":
        state = "CHECK_UNAVAILABLE"
        headline = "AI-origin checks are not active"
        summary = "No learned origin detector produced evidence for this scan."
        action = "Install and verify the model artifacts before using this lane in a demo."
    else:
        state = "ORIGIN_UNKNOWN"
        headline = "This scan cannot determine the image’s origin"
        summary = (
            "The available checks were too limited, unstable, low-resolution, or contradictory."
        )
        action = "Keep the case in review and collect another independent source of evidence."

    if trusted_ai_assertion:
        provenance_value = "Verified AI assertion"
        provenance_detail = "Trusted Content Credentials supplied direct provenance."
    elif ai_assertion:
        provenance_value = "AI assertion not trusted"
        provenance_detail = "An assertion exists, but signer trust was not established."
    else:
        provenance_value = "No verified AI assertion"
        provenance_detail = "Missing credentials do not imply human origin."

    if family_count == 0:
        model_value = "No model evidence"
        model_detail = "The origin lane is unavailable until a detector is activated."
    elif family_count == 1:
        model_value = "One evidence family"
        model_detail = "A single family can raise review, but cannot safely clear origin."
    else:
        model_value = f"{family_count} evidence families"
        model_detail = f"{calibrated_family_count} have held-out deployment calibration."

    if transform_stability is None:
        robustness_value = "Not measured"
        robustness_detail = "No detector completed the delivery stress views."
    elif transform_stability < 0.35:
        robustness_value = "Unstable"
        robustness_detail = "The response changed too much after JPEG, resize, or blur."
    else:
        robustness_value = "Stable"
        robustness_detail = "The recorded response survived common delivery changes."

    facts = [
        {
            "label": "Signed source information",
            "value": provenance_value,
            "detail": provenance_detail,
        },
        {"label": "Independent AI checks", "value": model_value, "detail": model_detail},
        {"label": "Result consistency", "value": robustness_value, "detail": robustness_detail},
    ]
    if visible_marker_supported:
        facts.insert(
            1,
            {
                "label": "Visible AI label",
                "value": "Label found",
                "detail": (
                    "The image contains a visible AI-use label; this can support review but can "
                    "be forged."
                ),
            },
        )

    return {
        "state": state,
        "tone": evidence_tier.lower(),
        "headline": headline,
        "summary": summary,
        "action": action,
        "show_domain_score": bool(show_domain_score and fused_score is not None),
        "domain_score": (
            round(fused_score, 6) if show_domain_score and fused_score is not None else None
        ),
        "domain_score_label": "CALIBRATED DOMAIN SCORE — NOT UNIVERSAL PROBABILITY",
        "facts": facts,
        "provenance_status": str(provenance_status),
    }


def analyze_synthetic_origin(
    *, image: Image.Image, detector_router, provenance, settings, visible_marker: dict | None = None
) -> dict:
    delivery_views = _delivery_views(image)
    spatial_views = (
        _spatial_views(image, settings.synthetic_spatial_crop_fraction)
        if getattr(settings, "synthetic_spatial_crops", True)
        else []
    )
    views = [*delivery_views, *spatial_views]
    member_rows: list[dict] = []
    errors: list[dict] = []

    for detector in detector_router.detectors:
        detector_started = time.monotonic()
        delivery_scores: list[float] = []
        delivery_weights: list[float] = []
        spatial_scores: list[float] = []
        metadata = None
        view_rows: list[dict] = []
        batch_used = callable(getattr(detector, "predict_many", None))
        if batch_used:
            try:
                detector_outputs = detector.predict_many([view for _, view, _, _ in views])
                if len(detector_outputs) != len(views):
                    raise RuntimeError("SYNTHETIC_BATCH_RESULT_COUNT_INVALID")
            except Exception as exc:
                detector_outputs = [exc] * len(views)
        else:
            detector_outputs = [None] * len(views)

        for index, (view_name, view, quality_weight, view_scope) in enumerate(views):
            result = detector_outputs[index]
            if result is None:
                try:
                    result = detector.predict(view)
                except Exception as exc:
                    result = exc
            if isinstance(result, Exception):
                errors.append(
                    {
                        "provider": detector.name,
                        "view": view_name,
                        "error_code": f"{type(result).__name__}",
                    }
                )
                continue
            output = result
            metadata = output
            raw_score = min(max(float(output.score), 0.0), 1.0)
            if output.calibrated:
                score = raw_score
                calibration = {
                    "applied": True,
                    "state": "PROVIDER_DECLARED_CALIBRATED",
                    "semantics": "PROVIDER_CALIBRATION_SCOPE_APPLIES",
                }
            elif hasattr(detector_router, "calibrate"):
                score, calibration = detector_router.calibrate(
                    output.provider,
                    output.model_version,
                    raw_score,
                )
            else:
                score = raw_score
                calibration = {
                    "applied": False,
                    "state": "NOT_AVAILABLE",
                    "semantics": "RAW_DETECTOR_SCORE_NOT_PROBABILITY",
                }
            if view_scope == "DELIVERY_TRANSFORM":
                delivery_scores.append(score)
                delivery_weights.append(quality_weight)
            else:
                spatial_scores.append(score)
            view_rows.append(
                {
                    "view": view_name,
                    "scope": view_scope,
                    "raw_score": round(raw_score, 6),
                    "score": round(score, 6),
                    "quality_weight": quality_weight,
                    "calibration": calibration,
                }
            )
        if not delivery_scores or metadata is None:
            continue
        global_score = _weighted_logit(delivery_scores, delivery_weights)
        view_std = float(np.std(delivery_scores))
        stability = max(0.0, 1.0 - view_std / max(settings.synthetic_max_view_std, 1e-6))
        spatial_consensus = float(np.median(spatial_scores)) if spatial_scores else None
        spatial_support_count = sum(
            score >= settings.synthetic_review_threshold for score in spatial_scores
        )
        required_spatial_support = min(3, len(spatial_scores))
        spatial_corroborated = bool(
            spatial_scores
            and spatial_support_count >= required_spatial_support
            and required_spatial_support >= 2
        )
        aggregate = (
            max(global_score, spatial_consensus)
            if spatial_corroborated and spatial_consensus is not None
            else global_score
        )
        member_rows.append(
            {
                "provider": metadata.provider,
                "model_version": metadata.model_version,
                "source_scope": metadata.source_scope,
                "evidence_family": metadata.evidence_family,
                "score_semantics": metadata.score_semantics,
                "calibrated": bool(
                    metadata.calibrated
                    or any(row["calibration"].get("applied") for row in view_rows)
                ),
                "calibration_state": view_rows[0]["calibration"].get("state"),
                "aggregate_score": round(aggregate, 6),
                "global_delivery_score": round(global_score, 6),
                "spatial_consensus_score": (
                    round(spatial_consensus, 6) if spatial_consensus is not None else None
                ),
                "spatial_support_count": spatial_support_count,
                "spatial_corroborated": spatial_corroborated,
                "view_standard_deviation": round(view_std, 6),
                "transform_stability": round(stability, 6),
                "views": view_rows,
                "warnings": list(metadata.warnings),
                "runtime_ms": round((time.monotonic() - detector_started) * 1000, 3),
                "inference_mode": "BATCHED_VIEWS" if batch_used else "RESIDENT_PER_VIEW",
            }
        )

    manifest = provenance.manifest_summary or {}
    ai_assertion = bool(manifest.get("ai_assertion_present"))
    trusted_ai_assertion = ai_assertion and provenance.status == ProvenanceStatus.VALID_TRUSTED
    valid_untrusted_ai_assertion = (
        ai_assertion and provenance.status == ProvenanceStatus.VALID_UNTRUSTED
    )
    visible_marker_supported, _marker_strength, _marker_confidence = _visible_marker_state(
        visible_marker
    )

    fused_score = None
    detector_disagreement = None
    transform_stability = None
    family_rows: list[dict] = []
    if member_rows:
        by_family: dict[str, list[dict]] = {}
        for row in member_rows:
            by_family.setdefault(str(row["evidence_family"]), []).append(row)
        for family, rows in by_family.items():
            aggregates = [float(row["aggregate_score"]) for row in rows]
            stabilities = [float(row["transform_stability"]) for row in rows]
            reliability = [
                (1.0 if row["calibrated"] else 0.78) * (0.45 + 0.55 * stability)
                for row, stability in zip(rows, stabilities, strict=True)
            ]
            family_rows.append(
                {
                    "family": family,
                    "score": round(_weighted_logit(aggregates, reliability), 6),
                    "calibrated": all(bool(row["calibrated"]) for row in rows),
                    "transform_stability": round(float(np.mean(stabilities)), 6),
                    "member_count": len(rows),
                    "providers": [str(row["provider"]) for row in rows],
                }
            )
        family_scores = [float(row["score"]) for row in family_rows]
        family_reliability = [
            (1.0 if row["calibrated"] else 0.78) * (0.45 + 0.55 * float(row["transform_stability"]))
            for row in family_rows
        ]
        fused_score = _weighted_logit(family_scores, family_reliability)
        detector_disagreement = float(np.std(family_scores)) if len(family_scores) > 1 else None
        transform_stability = float(
            np.average(
                [float(row["transform_stability"]) for row in family_rows],
                weights=family_reliability,
            )
        )

    short_side = min(image.size)
    low_quality = short_side < settings.synthetic_min_short_side
    unstable = bool(member_rows and transform_stability is not None and transform_stability < 0.35)
    high_disagreement = bool(detector_disagreement is not None and detector_disagreement >= 0.22)
    family_count = len(family_rows)
    calibrated_family_count = sum(bool(row["calibrated"]) for row in family_rows)
    stable_family_rows = [row for row in family_rows if float(row["transform_stability"]) >= 0.35]
    positive_family_count = sum(
        float(row["score"]) >= settings.synthetic_review_threshold for row in stable_family_rows
    )
    strong_family_count = sum(
        float(row["score"]) >= settings.synthetic_likely_threshold for row in stable_family_rows
    )
    calibrated_strong_family_count = sum(
        bool(row["calibrated"]) and float(row["score"]) >= settings.synthetic_likely_threshold
        for row in stable_family_rows
    )
    calibrated_positive_family_count = sum(
        bool(row["calibrated"]) and float(row["score"]) >= settings.synthetic_review_threshold
        for row in stable_family_rows
    )
    minimum_families = settings.synthetic_min_independent_families
    negative_clearance_supported = bool(
        family_count >= minimum_families
        and calibrated_family_count == family_count
        and all(float(row["score"]) < settings.synthetic_review_threshold for row in family_rows)
    )

    reasons: list[str] = []
    if trusted_ai_assertion:
        classification = "AI_PROVENANCE_CONFIRMED"
        evidence_tier = "PROVENANCE"
        review_recommended = True
        reasons.extend(["TRUSTED_C2PA_AI_ASSERTION", "AI_ORIGIN_IDENTIFIED_BY_PROVENANCE"])
    elif valid_untrusted_ai_assertion:
        classification = "AI_PROVENANCE_ASSERTED_UNTRUSTED_SIGNER"
        evidence_tier = "REVIEW"
        review_recommended = True
        reasons.extend(["C2PA_AI_ASSERTION_PRESENT", "C2PA_SIGNER_TRUST_NOT_CONFIRMED"])
    elif visible_marker_supported and calibrated_positive_family_count >= 1 and not unstable:
        classification = "AI_INDICATORS_CORROBORATED"
        evidence_tier = "HIGH"
        review_recommended = True
        reasons.extend(
            [
                "VISIBLE_AI_MARKER_AND_MODEL_SIGNAL_AGREE",
                "VISIBLE_MARKER_REQUIRES_REVIEW_NOT_PROVENANCE",
            ]
        )
    elif visible_marker_supported:
        classification = "AI_ORIGIN_MARKER_FOUND"
        evidence_tier = "REVIEW"
        review_recommended = True
        reasons.extend(
            [
                "VISIBLE_AI_MARKER_FOUND",
                "VISIBLE_MARKER_REQUIRES_REVIEW_NOT_PROVENANCE",
            ]
        )
    elif not member_rows:
        classification = "SYNTHETIC_ORIGIN_ANALYSIS_UNAVAILABLE"
        evidence_tier = "UNAVAILABLE"
        review_recommended = False
        reasons.append("NO_SYNTHETIC_DETECTOR_ACTIVE")
    elif low_quality:
        classification = "INCONCLUSIVE_LOW_RESOLUTION"
        evidence_tier = "INCONCLUSIVE"
        review_recommended = True
        reasons.extend(["IMAGE_TOO_SMALL_FOR_CONFIGURED_OPERATING_DOMAIN", "ABSTAINED"])
    elif unstable:
        classification = "INCONCLUSIVE_TRANSFORM_INSTABILITY"
        evidence_tier = "INCONCLUSIVE"
        review_recommended = True
        reasons.extend(["DETECTOR_UNSTABLE_ACROSS_COMMON_TRANSFORMS", "ABSTAINED"])
    elif high_disagreement:
        classification = "INCONCLUSIVE_DETECTOR_DISAGREEMENT"
        evidence_tier = "INCONCLUSIVE"
        review_recommended = True
        reasons.extend(["DETECTOR_ENSEMBLE_DISAGREEMENT", "ABSTAINED"])
    elif (
        fused_score is not None
        and fused_score >= settings.synthetic_likely_threshold
        and calibrated_strong_family_count >= minimum_families
        and calibrated_family_count == family_count
    ):
        classification = "LIKELY_AI_GENERATED"
        evidence_tier = "HIGH"
        review_recommended = True
        reasons.extend(["SYNTHETIC_DETECTOR_SUPPORT", "TRANSFORM_CONSISTENT_SUPPORT"])
    elif positive_family_count >= 1 or (
        fused_score is not None and fused_score >= settings.synthetic_review_threshold
    ):
        classification = "AI_ORIGIN_REVIEW_CANDIDATE"
        evidence_tier = "REVIEW"
        review_recommended = True
        reasons.append("SYNTHETIC_DETECTOR_REVIEW_RANGE")
        if family_count < minimum_families:
            reasons.append("INDEPENDENT_EVIDENCE_FAMILY_CORROBORATION_REQUIRED")
        if calibrated_family_count < family_count:
            reasons.append("DEPLOYMENT_CALIBRATION_INCOMPLETE")
    elif negative_clearance_supported:
        classification = "NO_AI_ORIGIN_EVIDENCE_DETECTED"
        evidence_tier = "LOW"
        review_recommended = False
        reasons.extend(["DETECTORS_DID_NOT_FIND_AI_ORIGIN_EVIDENCE", "NOT_PROOF_OF_HUMAN_ORIGIN"])
    else:
        classification = "AI_ORIGIN_INCONCLUSIVE_LIMITED_COVERAGE"
        evidence_tier = "INCONCLUSIVE"
        review_recommended = True
        reasons.extend(
            [
                "LOW_MODEL_RESPONSE_WITHOUT_NEGATIVE_CLEARANCE_SUPPORT",
                "ABSTAINED",
                "NOT_PROOF_OF_HUMAN_ORIGIN",
            ]
        )

    if len(member_rows) == 1:
        reasons.append("SINGLE_DETECTOR_LIMITATION")
    if family_count == 1:
        reasons.append("SINGLE_EVIDENCE_FAMILY_LIMITATION")
    if provenance.status == ProvenanceStatus.NOT_PRESENT:
        reasons.append("C2PA_ABSENCE_IS_NOT_HUMAN_ORIGIN_EVIDENCE")
    if errors:
        reasons.append("PARTIAL_DETECTOR_FAILURE")
    reasons.extend((visible_marker or {}).get("reason_codes") or [])

    show_domain_score = bool(
        fused_score is not None
        and family_count >= minimum_families
        and calibrated_family_count == family_count
    )
    presentation = _presentation(
        classification=classification,
        evidence_tier=evidence_tier,
        family_count=family_count,
        calibrated_family_count=calibrated_family_count,
        positive_family_count=positive_family_count,
        transform_stability=transform_stability,
        provenance_status=provenance.status,
        ai_assertion=ai_assertion,
        trusted_ai_assertion=trusted_ai_assertion,
        show_domain_score=show_domain_score,
        fused_score=fused_score,
        visible_marker_supported=visible_marker_supported,
    )
    scorecard = _origin_scorecard(
        fused_score=fused_score,
        family_count=family_count,
        calibrated_family_count=calibrated_family_count,
        minimum_families=minimum_families,
        review_threshold=settings.synthetic_review_threshold,
        transform_stability=transform_stability,
        negative_clearance_supported=negative_clearance_supported,
        trusted_ai_assertion=trusted_ai_assertion,
        valid_untrusted_ai_assertion=valid_untrusted_ai_assertion,
        visible_marker=visible_marker,
    )

    return {
        "schema": "creatorproof.synthetic_origin.v3",
        "classification": classification,
        "evidence_tier": evidence_tier,
        "review_recommended": review_recommended,
        "fused_detector_score": round(fused_score, 6) if fused_score is not None else None,
        "score_semantics": "QUALITY_WEIGHTED_ENSEMBLE_SCORE_NOT_PROBABILITY",
        "detector_count": len(member_rows),
        "evidence_family_count": family_count,
        "calibrated_family_count": calibrated_family_count,
        "positive_family_count": positive_family_count,
        "strong_family_count": strong_family_count,
        "calibrated_strong_family_count": calibrated_strong_family_count,
        "negative_clearance_supported": negative_clearance_supported,
        "detector_disagreement": (
            round(detector_disagreement, 6) if detector_disagreement is not None else None
        ),
        "transform_stability": (
            round(transform_stability, 6) if transform_stability is not None else None
        ),
        "image_operating_domain": {
            "width": image.width,
            "height": image.height,
            "minimum_short_side": settings.synthetic_min_short_side,
            "within_minimum_resolution": not low_quality,
        },
        "provenance_signal": {
            "status": provenance.status,
            "provider": provenance.provider,
            "ai_assertion_present": ai_assertion,
            "trusted_ai_assertion": trusted_ai_assertion,
        },
        "visible_marker_signal": visible_marker
        or {
            "provider": None,
            "available": False,
            "checked": False,
            "classification": "VISIBLE_MARKER_ANALYSIS_UNAVAILABLE",
            "supports_ai_origin_review": False,
            "markers": [],
            "reason_codes": ["VISIBLE_MARKER_PROVIDER_NOT_SUPPLIED"],
        },
        "scorecard": scorecard,
        "members": member_rows,
        "evidence_families": family_rows,
        "presentation": presentation,
        "forensic_diagnostics": _spectral_diagnostics(image),
        "runtime": {
            "view_count": len(views),
            "delivery_view_count": len(delivery_views),
            "spatial_view_count": len(spatial_views),
            "provider_timings_ms": {
                str(row["provider"]): row.get("runtime_ms") for row in member_rows
            },
            "provider_inference_modes": {
                str(row["provider"]): row.get("inference_mode") for row in member_rows
            },
        },
        "errors": errors,
        "reason_codes": list(dict.fromkeys(reasons)),
        "limitations": [
            "AI-origin detection is open-world; no detector is universally reliable.",
            "No-AI-evidence is not a claim that an image was created by a human.",
            "Model scores require generator-, domain-, and transformation-specific calibration.",
            "Frequency and residual diagnostics are descriptive and never decide origin alone.",
            "C2PA can confirm signed provenance claims but its absence is inconclusive.",
            (
                "Visible labels are forgeable review signals; their absence is never "
                "human-origin evidence."
            ),
        ],
    }
