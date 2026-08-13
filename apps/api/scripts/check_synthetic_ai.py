from __future__ import annotations

import json

from PIL import Image, ImageDraw

from app.core.config import Settings
from app.providers.synthetic_detection import SyntheticDetectorRouter
from app.services.model_bundle import load_model_bundle


def _diagnostic_image() -> Image.Image:
    image = Image.new("RGB", (512, 512), "#d8e0e8")
    draw = ImageDraw.Draw(image)
    for index in range(24):
        inset = 8 + index * 9
        draw.rectangle(
            (inset, inset, 511 - inset, 511 - inset),
            outline=(20 + index * 5, 70, 160),
            width=2,
        )
    draw.ellipse((140, 140, 372, 372), fill="#d98255", outline="#182638", width=8)
    return image


def main() -> int:
    settings = Settings()
    bundle = load_model_bundle(
        settings.model_bundle_path,
        strict=settings.model_bundle_strict,
    )
    router = SyntheticDetectorRouter(
        mode=settings.synthetic_detector,
        community_model_path=settings.synthetic_community_model_path,
        torchscript_model_path=settings.synthetic_torchscript_model_path,
        device=settings.synthetic_device,
        external_detectors_json=settings.synthetic_external_detectors_json,
        evidence_family_registry_path=settings.synthetic_evidence_family_registry_path,
        calibration_path=settings.synthetic_calibration_path,
        min_calibration_samples=settings.synthetic_min_calibration_samples,
        min_calibration_class_samples=settings.synthetic_min_calibration_class_samples,
        community_expected_sha256=(
            settings.synthetic_community_expected_sha256
            or bundle.declared_artifact_sha256("origin-community-forensics")
        ),
        calibration_domain_id=settings.synthetic_calibration_domain_id,
        crop_policy_id=settings.synthetic_crop_policy_id,
        model_bundle_manifest_digest=bundle.manifest_digest_sha256 or "",
        sightengine_api_user=settings.sightengine_api_user,
        sightengine_api_secret=settings.sightengine_api_secret,
        sightengine_timeout_seconds=settings.sightengine_timeout_seconds,
    )
    status = router.status()
    if not router.available:
        print(json.dumps(status, indent=2))
        return 1

    image = _diagnostic_image()
    rows = []
    failures = 0
    for detector in router.detectors:
        try:
            first = detector.predict(image)
            second = detector.predict(image)
        except Exception as exc:
            failures += 1
            rows.append(
                {
                    "provider": detector.name,
                    "runtime_check": "FAILED",
                    "error_code": f"{type(exc).__name__}:{exc}",
                    "note": "Provider failure is not a negative AI-origin result.",
                }
            )
            continue
        calibrated, calibration = router.calibrate(
            first.provider,
            first.model_version,
            first.score,
            first.artifact_sha256,
            first.preprocessing_identity,
        )
        rows.append(
            {
                "provider": first.provider,
                "evidence_family": first.evidence_family,
                "device": getattr(detector, "device", "external"),
                "raw_score": first.score,
                "score_semantics": first.score_semantics,
                "repeat_score": second.score,
                "deterministic_repeat": abs(first.score - second.score) <= 1e-7,
                "calibrated_score": calibrated if calibration["applied"] else None,
                "calibration": calibration,
                "note": (
                    "Diagnostic image has no origin label. This check validates loading and "
                    "repeatability only; it does not validate accuracy or turn a raw score into "
                    "a probability."
                ),
            }
        )
    print(
        json.dumps(
            {**status, "model_bundle": bundle.status(), "diagnostic": rows},
            indent=2,
        )
    )
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
