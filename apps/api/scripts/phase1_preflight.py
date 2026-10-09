"""Read-only Phase 1 configuration and dependency preflight.

No media is uploaded and no AI/Sightengine/marketplace quota is consumed.  Local
binary identity checks run by default; --live adds database/Redis connectivity.
Configured remote providers remain NOT_LIVE_CHECKED until an authorized scan or
investigation exercises their actual media/structured-output contract.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import create_engine, text

from app.core.config import Settings
from app.providers.provenance import C2PAToolProvenanceProvider
from app.services.aiand import AiAndClient
from app.services.model_bundle import load_model_bundle, validate_model_bundle_runtime

SCHEMA = "creatorproof.phase1_preflight.v1"


def _local_storage_ready(root: Path) -> bool:
    # Assess the existing directory or nearest existing ancestor without writing.
    current = root.resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current.is_dir() and os.access(current, os.R_OK | os.W_OK | os.X_OK)


def build_report(settings: Settings, *, live: bool = False) -> dict[str, Any]:
    binary = (
        C2PAToolProvenanceProvider(
            binary=settings.c2pa_binary,
            timeout_seconds=settings.c2pa_timeout_seconds,
            expected_version=settings.c2pa_expected_version,
            expected_binary_sha256=settings.c2pa_expected_binary_sha256,
            trust_policy_id=settings.c2pa_trust_policy_id,
        )
        if settings.c2pa_mode != "off"
        else None
    )
    sightengine_configured = bool(settings.sightengine_api_user and settings.sightengine_api_secret)
    providers = {
        "c2pa": {
            "configured": settings.c2pa_mode != "off",
            "available": bool(binary and binary.available),
            "state": "LOCAL_IDENTITY_VERIFIED" if binary and binary.available else "UNAVAILABLE",
            "reason_code": binary.unavailable_reason if binary else "C2PA_DISABLED",
            "version": binary.actual_version if binary else None,
            "binary_sha256": binary.actual_binary_sha256 if binary else None,
            "live_checked": False,
        },
        "sightengine": {
            "configured": sightengine_configured,
            "state": "CONFIGURED_NOT_LIVE_CHECKED" if sightengine_configured else "UNAVAILABLE",
            "live_checked": False,
            "reason_code": None if sightengine_configured else "SIGHTENGINE_CREDENTIALS_MISSING",
        },
        "assistant": {
            "configured": AiAndClient(settings).configured,
            "model": settings.aiand_model,
            "provider": "aiand",
            "state": "CONFIGURED_NOT_LIVE_CHECKED"
            if AiAndClient(settings).configured
            else "UNAVAILABLE",
            "live_checked": False,
            "reason_code": None if AiAndClient(settings).configured else "AIAND_NOT_CONFIGURED",
        },
        "unsplash": {
            "configured": bool(settings.unsplash_access_key),
            "state": "CONFIGURED_NOT_LIVE_CHECKED"
            if settings.unsplash_access_key
            else "UNAVAILABLE",
            "live_checked": False,
        },
        "pixabay": {
            "configured": bool(settings.pixabay_api_key),
            "state": "CONFIGURED_NOT_LIVE_CHECKED" if settings.pixabay_api_key else "UNAVAILABLE",
            "live_checked": False,
        },
    }
    dependencies: dict[str, Any] = {
        "database": {
            "backend": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql",
            "state": "NOT_LIVE_CHECKED",
        },
        "queue": {
            "backend": settings.job_backend,
            "state": "LOCAL_QUEUE_CONFIGURED"
            if settings.job_backend != "redis"
            else "NOT_LIVE_CHECKED",
        },
        "storage": {
            "backend": settings.storage_provider,
            "state": "LOCAL_PATH_ACCESSIBLE"
            if settings.storage_provider == "local" and _local_storage_ready(settings.storage_root)
            else "NOT_LIVE_CHECKED",
        },
    }
    failures: list[str] = []
    if live:
        # Refuse SQLite creation during a read-only check. Migrations/startup own
        # database creation; an empty configuration must not look operational.
        url = settings.database_url
        missing_sqlite = url.startswith("sqlite:///") and not Path(url[10:]).exists()
        if missing_sqlite and url != "sqlite:///:memory:":
            dependencies["database"]["state"] = "UNAVAILABLE"
            dependencies["database"]["reason_code"] = "DATABASE_NOT_INITIALIZED"
            failures.append("DATABASE_NOT_INITIALIZED")
        else:
            engine = None
            try:
                options = {"connect_timeout": 5} if not url.startswith("sqlite") else {"timeout": 5}
                engine = create_engine(url, connect_args=options)
                with engine.connect() as connection:
                    connection.execute(text("SELECT 1"))
                dependencies["database"]["state"] = "LIVE_REACHABLE"
            except Exception:
                dependencies["database"]["state"] = "UNAVAILABLE"
                dependencies["database"]["reason_code"] = "DATABASE_CONNECTION_FAILED"
                failures.append("DATABASE_CONNECTION_FAILED")
            finally:
                if engine is not None:
                    engine.dispose()
        if settings.job_backend == "redis":
            try:
                import redis

                connection = redis.Redis.from_url(
                    settings.redis_url, socket_timeout=5, socket_connect_timeout=5
                )
                try:
                    connection.ping()
                finally:
                    connection.close()
                dependencies["queue"]["state"] = "LIVE_REACHABLE"
            except Exception:
                dependencies["queue"]["state"] = "UNAVAILABLE"
                failures.append("REDIS_CONNECTION_FAILED")
    bundle_validation: dict[str, Any] | None = None
    try:
        bundle = load_model_bundle(settings.model_bundle_path, strict=True)
        bundle_validation = validate_model_bundle_runtime(
            bundle,
            runtime_lock_path=settings.runtime_lock_path,
            artifact_paths={
                "copy-retrieval-sscd": settings.sscd_model_path,
                "origin-community-forensics": settings.synthetic_community_model_path,
                "style-csd": settings.style_csd_model_path,
            },
        )
    except ValueError:
        failures.append("MODEL_BUNDLE_INVALID")
    warnings = [
        f"{name.upper()}_UNAVAILABLE"
        for name, value in providers.items()
        if not value["configured"] or name == "c2pa" and not value["available"]
    ]
    if settings.candidate_retention_seconds == 0:
        warnings.append("CANDIDATE_MEDIA_DELETED_AFTER_SCAN")
    return {
        "schema": SCHEMA,
        "valid": not failures,
        "live": live,
        "providers": providers,
        "dependencies": dependencies,
        "failures": failures,
        "warnings": warnings,
        "model_bundle_validation": bundle_validation,
        "privacy": {
            "candidate_retention_seconds": settings.candidate_retention_seconds,
            "secrets_included": False,
        },
        "claim_boundary": (
            "Configuration and binary identity do not prove provider availability, accuracy, "
            "ownership, infringement, or production readiness. --live probes only database "
            "and Redis connectivity; use an authorized scan/investigation for provider contracts."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Probe database and Redis connectivity")
    parser.add_argument(
        "--require",
        action="append",
        choices=["c2pa", "sightengine", "assistant", "unsplash", "pixabay"],
        default=[],
        help="Fail if the named optional capability is unconfigured",
    )
    args = parser.parse_args()
    try:
        settings = Settings()
        report = build_report(settings, live=args.live)
    except ValidationError as exc:
        # Pydantic's default string form includes input values. Emit field names
        # and types only so a malformed secret can never reach console output.
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "valid": False,
                    "failures": [
                        {"field": ".".join(str(part) for part in item["loc"]), "type": item["type"]}
                        for item in exc.errors(include_input=False, include_context=False)
                    ],
                },
                sort_keys=True,
            )
        )
        return 2
    unmet = [
        name
        for name in args.require
        if not report["providers"][name]["configured"]
        or name == "c2pa"
        and not report["providers"][name]["available"]
    ]
    report["required_capabilities_unmet"] = unmet
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report["valid"] and not unmet else 3


if __name__ == "__main__":
    raise SystemExit(main())
