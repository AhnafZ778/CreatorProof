from __future__ import annotations

import json

from PIL import Image, ImageDraw

from app.core.config import Settings
from app.providers.synthetic_detection import SyntheticDetectorRouter


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
    router = SyntheticDetectorRouter(
        mode=settings.synthetic_detector,
        community_model_path=settings.synthetic_community_model_path,
        torchscript_model_path=settings.synthetic_torchscript_model_path,
        device=settings.synthetic_device,
        external_detectors_json=settings.synthetic_external_detectors_json,
        calibration_path=settings.synthetic_calibration_path,
        min_calibration_samples=settings.synthetic_min_calibration_samples,
        min_calibration_class_samples=settings.synthetic_min_calibration_class_samples,
    )
    status = router.status()
    if not router.available:
        print(json.dumps(status, indent=2))
        return 1

    image = _diagnostic_image()
    rows = []
    for detector in router.detectors:
        first = detector.predict(image)
        second = detector.predict(image)
        calibrated, calibration = router.calibrate(
            first.provider,
            first.model_version,
            first.score,
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
    print(json.dumps({**status, "diagnostic": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
