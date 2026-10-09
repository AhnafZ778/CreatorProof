"""Typed rights preferences and interoperable export adapters.

Exports describe a recorded preference. They neither create a licence nor make
an ownership assertion independently verified. Reference formats are pinned in
the export metadata so changes to draft vocabularies are deliberate.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.canonical import canonical_digest


class PermissionValue(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    LICENSE_REQUIRED = "LICENSE_REQUIRED"
    REVIEW = "REVIEW"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


PERMISSION_FIELDS = (
    "search_indexing_permission",
    "commercial_search_permission",
    "AI_training_permission",
    "noncommercial_training_permission",
    "commercial_training_permission",
    "fine_tuning_permission",
    "style_reference_permission",
    "image_to_image_permission",
    "image_editing_permission",
    "derivative_generation_permission",
    "likeness_use_permission",
)
PERMISSION_ALIASES = {
    "search": "search_indexing_permission",
    "search_indexing": "search_indexing_permission",
    "commercial_search": "commercial_search_permission",
    "ai_training": "AI_training_permission",
    "ai_training_permission": "AI_training_permission",
    "training": "AI_training_permission",
    "noncommercial_training": "noncommercial_training_permission",
    "commercial_training": "commercial_training_permission",
    "fine_tuning": "fine_tuning_permission",
    "style_reference": "style_reference_permission",
    "image_to_image": "image_to_image_permission",
    "image_editing": "image_editing_permission",
    "derivative_generation": "derivative_generation_permission",
    "likeness_use": "likeness_use_permission",
}


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def iso(value: datetime | None) -> str | None:
    normalized = utc(value)
    return normalized.isoformat() if normalized else None


class PassportDimensions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribution_required: bool | None = None
    attribution_text: str | None = Field(default=None, max_length=1000)
    license_required: bool | None = None
    license_contact: str | None = Field(default=None, max_length=512)
    minimum_license_fee: str | None = Field(
        default=None, pattern=r"^\d{1,12}(?:\.\d{1,4})?$", max_length=17
    )
    license_fee_currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    geographic_scope: list[str] = Field(default_factory=list, max_length=250)
    permitted_platforms: list[str] = Field(default_factory=list, max_length=100)
    prohibited_platforms: list[str] = Field(default_factory=list, max_length=100)
    permitted_models: list[str] = Field(default_factory=list, max_length=100)
    prohibited_models: list[str] = Field(default_factory=list, max_length=100)
    channels: list[str] = Field(default_factory=list, max_length=100)
    audiences: list[str] = Field(default_factory=list, max_length=100)
    transformations: list[str] = Field(default_factory=list, max_length=100)
    # Origin-relative publisher path for export installation; never a fetch URL.
    asset_path: str | None = Field(default=None, max_length=1024)
    policy_notes: str | None = Field(default=None, max_length=4000)
    # Broad TDM rights reservation is separate from a narrow AI-training preference.
    tdm_reservation: Literal[0, 1] | None = None

    @field_validator("tdm_reservation", mode="before")
    @classmethod
    def explicit_tdm_boolean_integer(cls, value):
        if value is not None and (type(value) is not int or value not in {0, 1}):
            raise ValueError("tdm_reservation must be the integer 0 or 1")
        return value

    @field_validator(
        "geographic_scope",
        "permitted_platforms",
        "prohibited_platforms",
        "permitted_models",
        "prohibited_models",
        "channels",
        "audiences",
        "transformations",
    )
    @classmethod
    def normalized_scope(cls, values: list[str]) -> list[str]:
        if any(
            not value.strip() or len(value) > 160 or any(ord(c) < 32 for c in value)
            for value in values
        ):
            raise ValueError(
                "Scope entries must be bounded nonempty text without control characters"
            )
        return sorted(set(value.strip() for value in values))

    @field_validator("geographic_scope")
    @classmethod
    def geographic_codes(cls, values: list[str]) -> list[str]:
        normalized = [value.upper() for value in values]
        if any(
            value != "*" and (len(value) != 2 or not value.isascii() or not value.isalpha())
            for value in normalized
        ):
            raise ValueError("geographic_scope entries must be two-letter country codes or *")
        return sorted(set(normalized))

    @field_validator("license_contact")
    @classmethod
    def safe_contact(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(c) < 32 for c in value):
            raise ValueError("license_contact cannot contain control characters")
        if value.startswith(("https://", "mailto:")):
            return value
        raise ValueError("license_contact must use https:// or mailto:")

    @field_validator("asset_path")
    @classmethod
    def safe_asset_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or parsed.query
            or parsed.fragment
            or any(c in value for c in "\r\n *\\")
        ):
            raise ValueError(
                "asset_path must be an exact origin-relative path without wildcards or query data"
            )
        return value

    @model_validator(mode="after")
    def consistent_scope(self):
        for permitted, prohibited in (
            (self.permitted_models, self.prohibited_models),
            (self.permitted_platforms, self.prohibited_platforms),
        ):
            if set(permitted) & set(prohibited):
                raise ValueError(
                    "The same model or platform cannot be both permitted and prohibited"
                )
        if self.minimum_license_fee and not self.license_fee_currency:
            raise ValueError("minimum_license_fee requires license_fee_currency")
        return self


class RightsPolicyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    creator_id: str | None = Field(default=None, max_length=64)
    permissions: dict[str, PermissionValue] = Field(
        default_factory=dict, max_length=len(PERMISSION_FIELDS)
    )
    dimensions: PassportDimensions = Field(default_factory=PassportDimensions)
    search_indexing_permission: PermissionValue | None = None
    commercial_search_permission: PermissionValue | None = None
    AI_training_permission: PermissionValue | None = None
    noncommercial_training_permission: PermissionValue | None = None
    commercial_training_permission: PermissionValue | None = None
    fine_tuning_permission: PermissionValue | None = None
    style_reference_permission: PermissionValue | None = None
    image_to_image_permission: PermissionValue | None = None
    image_editing_permission: PermissionValue | None = None
    derivative_generation_permission: PermissionValue | None = None
    likeness_use_permission: PermissionValue | None = None
    attribution_required: bool | None = None
    attribution_text: str | None = Field(default=None, max_length=1000)
    license_required: bool | None = None
    license_contact: str | None = Field(default=None, max_length=512)
    minimum_license_fee: str | None = Field(default=None, max_length=17)
    license_fee_currency: str | None = None
    geographic_scope: list[str] | None = None
    permitted_platforms: list[str] | None = None
    prohibited_platforms: list[str] | None = None
    permitted_models: list[str] | None = None
    prohibited_models: list[str] | None = None
    policy_notes: str | None = Field(default=None, max_length=4000)
    consent_status: Literal["GRANTED", "NOT_GRANTED", "WITHDRAWN", "UNKNOWN"] = "UNKNOWN"
    consent_source: str | None = Field(default=None, max_length=512)
    consent_timestamp: datetime | None = None
    revocation_status: Literal["NOT_REVOKED", "REVOKED", "UNKNOWN"] = "NOT_REVOKED"
    revocation_timestamp: datetime | None = None
    creator_assertion_status: Literal["SELF_DECLARED", "UNKNOWN"] = "SELF_DECLARED"
    # This is intentionally an assertion envelope rather than a writable verified state.
    creator_assertion: dict[str, str] = Field(default_factory=dict, max_length=20)
    consent: dict[str, str] = Field(default_factory=dict, max_length=10)
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    @field_validator("permissions")
    @classmethod
    def permission_names(cls, values: dict[str, PermissionValue]) -> dict[str, PermissionValue]:
        result = {}
        for key, value in values.items():
            normalized = PERMISSION_ALIASES.get(key, key)
            if normalized not in PERMISSION_FIELDS:
                raise ValueError(f"Unknown rights permission: {key}")
            if normalized in result and result[normalized] != value:
                raise ValueError(f"Conflicting permission aliases: {key}")
            result[normalized] = value
        return result

    @field_validator("creator_assertion", "consent")
    @classmethod
    def bounded_assertions(cls, values: dict[str, str]) -> dict[str, str]:
        if any(len(key) > 80 or len(value) > 1000 for key, value in values.items()):
            raise ValueError("Assertion metadata exceeds its bounds")
        return values

    @model_validator(mode="after")
    def consistent_record(self):
        if (
            self.effective_from
            and self.effective_until
            and utc(self.effective_until) <= utc(self.effective_from)
        ):
            raise ValueError("effective_until must follow effective_from")
        if self.revocation_status == "REVOKED" and self.revocation_timestamp is None:
            raise ValueError("A revoked policy requires revocation_timestamp")
        now = datetime.now(UTC)
        if self.revocation_timestamp and utc(self.revocation_timestamp) > now:
            raise ValueError("revocation_timestamp cannot describe a future revocation")
        if self.consent_status == "GRANTED" and (
            not self.consent_source or self.consent_timestamp is None
        ):
            raise ValueError("Granted consent requires a source and timestamp")
        if self.consent_timestamp and utc(self.consent_timestamp) > now:
            raise ValueError("consent_timestamp cannot describe future consent")
        for field in PERMISSION_FIELDS:
            explicit = getattr(self, field)
            if (
                explicit is not None
                and field in self.permissions
                and self.permissions[field] != explicit
            ):
                raise ValueError(f"Conflicting {field} values")
        # Revalidate merged top-level compatibility fields with the same typed rules.
        self.normalized_dimensions()
        return self

    def normalized_permissions(self) -> dict[str, str]:
        result = {
            field: str(self.permissions.get(field, PermissionValue.UNKNOWN))
            for field in PERMISSION_FIELDS
        }
        for field in PERMISSION_FIELDS:
            explicit = getattr(self, field)
            if explicit is not None:
                result[field] = str(explicit)
        return result

    def normalized_dimensions(self) -> dict[str, Any]:
        values = self.dimensions.model_dump(mode="json")
        for field in PassportDimensions.model_fields:
            explicit = getattr(self, field, None)
            if explicit is not None:
                if field in self.dimensions.model_fields_set and values[field] != explicit:
                    raise ValueError(f"Conflicting dimension: {field}")
                values[field] = explicit
        return PassportDimensions.model_validate(values).model_dump(mode="json")

    def assertions(self) -> dict[str, Any]:
        return {
            "creator_id": self.creator_id,
            "status": self.creator_assertion_status,
            "assertion": self.creator_assertion,
        }

    def consent_metadata(self) -> dict[str, Any]:
        return {
            "status": self.consent_status,
            "source": self.consent_source,
            "timestamp": iso(self.consent_timestamp),
            "assertion": self.consent,
        }

    def revocation_metadata(self) -> dict[str, Any]:
        return {"status": self.revocation_status, "timestamp": iso(self.revocation_timestamp)}


def policy_integrity_projection(row) -> dict[str, Any]:
    return {
        "schema": "creatorproof.rights-policy.v1",
        "work_id": row.work_id,
        "version": row.version,
        "permissions": row.permissions or {},
        "dimensions": row.dimensions or {},
        "creator_assertions": row.creator_assertions or {},
        "consent_metadata": row.consent_metadata or {},
        "revocation_metadata": row.revocation_metadata or {},
        "corroboration": row.corroboration or [],
        "effective_from": iso(row.effective_from),
        "effective_until": iso(row.effective_until),
    }


def policy_state(row, *, now: datetime | None = None) -> str:
    if row is None:
        return "UNKNOWN"
    now = utc(now or datetime.now(UTC))
    if (row.revocation_metadata or {}).get("status") == "REVOKED":
        return "REVOKED"
    if (row.consent_metadata or {}).get("status") == "WITHDRAWN":
        return "CONSENT_WITHDRAWN"
    if (row.consent_metadata or {}).get("status") == "NOT_GRANTED":
        return "CONSENT_NOT_GRANTED"
    if row.effective_until and utc(row.effective_until) <= now:
        return "EXPIRED"
    if row.effective_from and utc(row.effective_from) > now:
        return "NOT_YET_EFFECTIVE"
    if canonical_digest(policy_integrity_projection(row)) != row.digest_sha256:
        return "INTEGRITY_MISMATCH"
    return "ACTIVE"


def permission(row, name: str) -> str:
    if policy_state(row) != "ACTIVE":
        return "UNKNOWN"
    values = row.permissions or {}
    return str(values.get(name) or "UNKNOWN")


def _qualified_policy(row) -> bool:
    """A coarse yes/no export must not erase a recorded condition."""
    return bool(
        row
        and (
            (row.dimensions or {}).get("tdm_reservation") == 1
            or any(
                (row.dimensions or {}).get(key)
                for key in (
                    "geographic_scope",
                    "permitted_models",
                    "prohibited_models",
                    "permitted_platforms",
                    "prohibited_platforms",
                    "channels",
                    "audiences",
                    "transformations",
                    "attribution_required",
                    "license_required",
                    "minimum_license_fee",
                )
            )
        )
    )


def aipref_export(row) -> dict[str, Any]:
    """IETF draft categories are deliberately broader than passport fields.

    Qualified licence/review/territory states cannot be represented by an
    unconditional y/n preference, so they remain omitted (unknown).
    """
    mappings = {
        "train-ai": [
            "AI_training_permission",
            "commercial_training_permission",
            "noncommercial_training_permission",
            "fine_tuning_permission",
        ],
        "search": ["search_indexing_permission", "commercial_search_permission"],
        "ai-use": [
            "style_reference_permission",
            "image_to_image_permission",
            "image_editing_permission",
            "derivative_generation_permission",
        ],
    }
    preferences = {}
    unresolved = []
    qualified = _qualified_policy(row)
    for category, fields in mappings.items():
        values = [permission(row, field) if row is not None else "UNKNOWN" for field in fields]
        if qualified:
            unresolved.append(category)
        elif "DENY" in values:
            preferences[category] = "n"
        elif all(value == "ALLOW" for value in values):
            preferences[category] = "y"
        else:
            unresolved.append(category)
    return {
        "format": "IETF_AIPREF_VOCABULARY_DRAFT_2026_09_14",
        "specification": "https://ietf-wg-aipref.github.io/drafts/draft-ietf-aipref-vocab.html",
        "status": "WORK_IN_PROGRESS",
        "preferences": preferences,
        "serialized": ", ".join(f"{key}={value}" for key, value in sorted(preferences.items())),
        "unrepresented_categories": unresolved,
    }


def commercial_training_preference(row) -> str:
    specific = permission(row, "commercial_training_permission") if row else "UNKNOWN"
    if specific == "UNKNOWN":
        specific = permission(row, "AI_training_permission") if row else "UNKNOWN"
    if specific == "ALLOW" and (row.dimensions or {}).get("license_required"):
        return "LICENSE_REQUIRED"
    return specific


def _broad_training_preference(row) -> str:
    values = [
        permission(row, field)
        for field in (
            "AI_training_permission",
            "commercial_training_permission",
            "fine_tuning_permission",
        )
    ]
    if "DENY" in values:
        return "DENY"
    if "LICENSE_REQUIRED" in values or (row and (row.dimensions or {}).get("license_required")):
        return "LICENSE_REQUIRED"
    return "ALLOW" if all(value == "ALLOW" for value in values) else "UNKNOWN"


def ai_txt_export(row, *, work_id: str) -> str:
    path = (row.dimensions or {}).get("asset_path") if row else None
    selected = _broad_training_preference(row)
    lines = [
        "# Spawning ai.txt export",
        f"# CreatorProof identifier: {work_id}",
        f"# Policy state: {policy_state(row)}",
        "# Install on the publisher origin at /ai.txt; this endpoint does not publish it there.",
        "User-Agent: *",
    ]
    qualified = _qualified_policy(row)
    if path and not qualified and selected in {"ALLOW", "DENY", "LICENSE_REQUIRED"}:
        lines.append(f"{'Allow' if selected == 'ALLOW' else 'Disallow'}: {path}")
    else:
        lines.append("# No unconditional directive: preference or publisher asset path is unknown.")
    return "\n".join(lines) + "\n"


def tdm_export(row, *, work_id: str, policy_url: str | None = None) -> dict[str, Any]:
    """Do not turn absent/unknown preferences into an affirmative opt-in."""
    explicit = (row.dimensions or {}).get("tdm_reservation") if row else None
    fields = (
        "AI_training_permission",
        "commercial_training_permission",
        "noncommercial_training_permission",
        "fine_tuning_permission",
        "search_indexing_permission",
        "commercial_search_permission",
    )
    values = [permission(row, field) if row else "UNKNOWN" for field in fields]
    reservation = None
    reasons = []
    if policy_state(row) != "ACTIVE":
        reasons.append("POLICY_NOT_ACTIVE")
    elif _qualified_policy(row) or any(value in {"DENY", "LICENSE_REQUIRED"} for value in values):
        reservation = 1
        reasons.append("CONDITIONS_OR_RESTRICTED_DECLARED_USE_REQUIRE_RESERVATION")
    elif explicit == 1:
        reservation = 1
        reasons.append("EXPLICIT_BROAD_TDM_RESERVATION")
    elif explicit == 0 and not any(value == "REVIEW" for value in values):
        reservation = 0
        reasons.append("EXPLICIT_BROAD_TDM_NONRESERVATION")
    else:
        reasons.append("NO_UNQUALIFIED_EXPLICIT_BROAD_TDM_PREFERENCE")
    return {
        "schema": "creatorproof.tdm-policy.v1",
        "specification": "https://www.w3.org/community/reports/tdmrep/CG-FINAL-tdmrep-20240510/",
        "specification_status": "W3C_COMMUNITY_GROUP_REPORT",
        "work_id": work_id,
        "tdm-reservation": reservation,
        "recorded_tdm_reservation": explicit,
        "mapping_reason_codes": reasons,
        "tdm-policy": policy_url if reservation == 1 else None,
        "policy_state": policy_state(row),
        "policy_digest_sha256": row.digest_sha256 if row else None,
        "conditions": row.dimensions if row else {},
        "protocol_headers": {
            "tdm-reservation": str(reservation),
            **({"tdm-policy": policy_url} if reservation == 1 and policy_url else {}),
        }
        if reservation is not None
        else {},
        "limitations": "An export communicates a preference. It does not prevent use, "
        "create permission, or determine legal rights.",
    }


def c2pa_usage_export(row) -> dict[str, Any]:
    # C2PA 2.3 removed the deprecated training-mining assertion. The current
    # backend is read-only and does not sign/modify assets: report that honestly.
    return {
        "supported": False,
        "status": "UNSUPPORTED",
        "reason_codes": ["C2PA_USAGE_ASSERTION_AUTHORING_NOT_SUPPORTED_BY_READ_ONLY_PROVIDER"],
        "specification": "https://spec.c2pa.org/specifications/specifications/2.3/specs/C2PA_Specification.html",
        "policy_digest_sha256": row.digest_sha256 if row else None,
        "assertions": [],
    }


def export_headers(payload: Any) -> dict[str, str]:
    digest = canonical_digest(payload)
    return {
        "ETag": f'"{digest}"',
        "X-CreatorProof-Digest-SHA256": digest,
        "Cache-Control": "private, no-cache",
    }


def public_asset_id(resource_type: str, resource_id: str) -> str:
    return (
        "cp_"
        + hashlib.sha256(
            f"creatorproof.public-asset.v1:{resource_type}:{resource_id}".encode()
        ).hexdigest()[:40]
    )
