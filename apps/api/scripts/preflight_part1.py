from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import shutil
from pathlib import Path

from app.core.config import Settings
from app.services.model_bundle import (
    QUALIFICATION_STATES,
    load_model_bundle,
    validate_model_bundle_runtime,
)
from app.services.style_profiles import load_style_profile_registry


def _package_version(distribution: str) -> str | None:
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate Part 1 identities and capability readiness without analysing media."
    )
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--runtime-lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--require-state", choices=QUALIFICATION_STATES)
    args = parser.parse_args()

    settings = Settings()
    manifest_path = args.manifest or settings.model_bundle_path
    try:
        bundle = load_model_bundle(manifest_path, strict=True)
        profiles = load_style_profile_registry(
            settings.style_profile_manifest_path,
            strict=settings.style_profile_manifest_strict,
        )
    except ValueError as exc:
        print(
            json.dumps(
                {"schema": "creatorproof.part1_preflight.v1", "valid": False, "error": str(exc)},
                indent=2,
            )
        )
        return 2

    runtime = validate_model_bundle_runtime(
        bundle,
        runtime_lock_path=args.runtime_lock,
        artifact_paths={
            "copy-retrieval-sscd": settings.sscd_model_path,
            "origin-community-forensics": settings.synthetic_community_model_path,
            "style-csd": settings.style_csd_model_path,
        },
    )
    requirement_met = True
    if args.require_state:
        requirement_met = (
            QUALIFICATION_STATES.index(bundle.qualification_state)
            >= QUALIFICATION_STATES.index(args.require_state)
            and runtime["runtime_requirement_met_for_declared_state"]
        )
    report = {
        "schema": "creatorproof.part1_preflight.v1",
        "valid": True,
        "requirement_met": requirement_met,
        "preflight_state": (
            "DECLARED_STATE_VERIFIED"
            if runtime["runtime_requirement_met_for_declared_state"]
            else "DECLARED_STATE_REQUIREMENTS_NOT_MET"
        ),
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                "opencv-python-headless": _package_version("opencv-python-headless"),
                "torch": _package_version("torch"),
                "fastapi": _package_version("fastapi"),
            },
            "binaries": {
                "c2patool": shutil.which(settings.c2pa_binary),
                "tesseract": shutil.which(settings.visible_ai_marker_binary),
            },
        },
        "model_bundle_validation": runtime,
        "style_profile_registry": profiles.status(),
        "claim_boundary": (
            "Preflight verifies declared identities and availability; it is not an accuracy, "
            "legal, ownership, authorship, or production-readiness claim."
        ),
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if requirement_met else 3


if __name__ == "__main__":
    raise SystemExit(main())
