from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app.services.model_bundle import canonical_json_digest

STYLE_PROFILE_MANIFEST_SCHEMA = "creatorproof.style_profile_manifest.v1"
CONSENT_STATES = ("CONFIRMED", "NOT_CONFIRMED", "REVOKED")


@dataclass(frozen=True, slots=True)
class StyleProfileBinding:
    profile_id: str
    profile_version: str
    display_name: str
    consent_state: str
    consent_reference: str
    enrollment_method: str
    work_ids: tuple[str, ...]

    @property
    def profile_key(self) -> str:
        return f"profile:{self.profile_id}:{self.profile_version}"

    @property
    def authorized(self) -> bool:
        return self.consent_state == "CONFIRMED"

    def public_record(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "display_name": self.display_name,
            "consent_state": self.consent_state,
            "consent_reference": self.consent_reference,
            "enrollment_method": self.enrollment_method,
            "profile_authorized": self.authorized,
            "profile_source": "REGISTERED_CONSENT_MANIFEST",
        }


@dataclass(frozen=True, slots=True)
class StyleProfileRegistry:
    state: str
    manifest_id: str
    manifest_path: str
    manifest_digest_sha256: str | None
    profiles: tuple[StyleProfileBinding, ...]
    reason_codes: tuple[str, ...]

    @classmethod
    def unavailable(cls, path: Path, reason_code: str) -> StyleProfileRegistry:
        return cls(
            state="NOT_CONFIGURED",
            manifest_id="creatorproof-style-profiles-unavailable",
            manifest_path=str(path),
            manifest_digest_sha256=None,
            profiles=(),
            reason_codes=(reason_code,),
        )

    def binding_for_work(self, work_id: str) -> StyleProfileBinding | None:
        return next(
            (profile for profile in self.profiles if work_id in profile.work_ids),
            None,
        )

    def status(self) -> dict:
        return {
            "state": self.state,
            "manifest_id": self.manifest_id,
            "manifest_path": self.manifest_path,
            "manifest_digest_sha256": self.manifest_digest_sha256,
            "profile_count": len(self.profiles),
            "authorized_profile_count": sum(profile.authorized for profile in self.profiles),
            "reason_codes": list(self.reason_codes),
        }


def _required_text(payload: dict, keys: tuple[str, ...], scope: str) -> dict[str, str]:
    result = {key: str(payload.get(key) or "").strip() for key in keys}
    missing = [key for key, value in result.items() if not value]
    if missing:
        raise ValueError(f"{scope} missing required fields: {','.join(missing)}")
    return result


def _parse_profile(payload: dict, index: int) -> StyleProfileBinding:
    scope = f"profile[{index}]"
    text = _required_text(
        payload,
        ("profile_id", "profile_version", "display_name", "enrollment_method"),
        scope,
    )
    consent = payload.get("consent")
    if not isinstance(consent, dict):
        raise ValueError(f"{scope}.consent must be an object")
    consent_text = _required_text(consent, ("state", "reference"), f"{scope}.consent")
    if consent_text["state"] not in CONSENT_STATES:
        raise ValueError(f"{scope}.consent.state is unsupported")
    work_ids = payload.get("work_ids")
    if not isinstance(work_ids, list) or not work_ids:
        raise ValueError(f"{scope}.work_ids must be a non-empty array")
    normalized_work_ids = tuple(str(work_id).strip() for work_id in work_ids)
    if any(not work_id for work_id in normalized_work_ids):
        raise ValueError(f"{scope}.work_ids must contain non-empty strings")
    if len(normalized_work_ids) != len(set(normalized_work_ids)):
        raise ValueError(f"{scope}.work_ids must be unique")
    return StyleProfileBinding(
        profile_id=text["profile_id"],
        profile_version=text["profile_version"],
        display_name=text["display_name"],
        consent_state=consent_text["state"],
        consent_reference=consent_text["reference"],
        enrollment_method=text["enrollment_method"],
        work_ids=normalized_work_ids,
    )


def load_style_profile_registry(
    path: Path,
    *,
    strict: bool = False,
) -> StyleProfileRegistry:
    path = Path(path)
    if not path.is_file():
        if strict:
            raise ValueError(f"Style profile manifest not found: {path}")
        return StyleProfileRegistry.unavailable(path, "STYLE_PROFILE_MANIFEST_NOT_FOUND")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != STYLE_PROFILE_MANIFEST_SCHEMA:
            raise ValueError("unsupported style profile manifest schema")
        manifest_id = str(payload.get("manifest_id") or "").strip()
        if not manifest_id:
            raise ValueError("style profile manifest_id is required")
        raw_profiles = payload.get("profiles")
        if not isinstance(raw_profiles, list):
            raise ValueError("style profile profiles must be an array")
        if not all(isinstance(profile, dict) for profile in raw_profiles):
            raise ValueError("every style profile must be an object")
        profiles = tuple(
            _parse_profile(profile, index) for index, profile in enumerate(raw_profiles)
        )
        profile_ids = [profile.profile_id for profile in profiles]
        work_ids = [work_id for profile in profiles for work_id in profile.work_ids]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("style profile_id values must be unique")
        if len(work_ids) != len(set(work_ids)):
            raise ValueError("a work_id cannot be enrolled in multiple style profiles")
        return StyleProfileRegistry(
            state="VALID",
            manifest_id=manifest_id,
            manifest_path=str(path),
            manifest_digest_sha256=canonical_json_digest(payload),
            profiles=profiles,
            reason_codes=(),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if strict:
            raise ValueError(
                f"Invalid style profile manifest: {type(exc).__name__}: {exc}"
            ) from exc
        return StyleProfileRegistry.unavailable(
            path,
            f"STYLE_PROFILE_MANIFEST_INVALID:{type(exc).__name__}",
        )
