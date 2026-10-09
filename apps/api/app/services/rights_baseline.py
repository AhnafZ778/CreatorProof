"""Create a neutral versioned rights record without inventing creator consent."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, RightsPolicyVersion, Work
from app.services.canonical import canonical_digest
from app.services.rights_passport import (
    PERMISSION_FIELDS,
    RightsPolicyPayload,
    policy_integrity_projection,
    utc,
)

UNKNOWN_BASELINE_SOURCE = "SYSTEM_REGISTRATION_UNKNOWN"


def is_unknown_rights_baseline(row) -> bool:
    """A server baseline conveys absence of instructions, never authorization."""
    return bool(
        row
        and (row.creator_assertions or {}).get("baseline_source") == UNKNOWN_BASELINE_SOURCE
        and (row.creator_assertions or {}).get("status") == "UNKNOWN"
        and all((row.permissions or {}).get(field) == "UNKNOWN" for field in PERMISSION_FIELDS)
    )


def ensure_unknown_rights_baseline(
    db: Session,
    *,
    work: Work,
    created_by_principal_id: str | None = None,
    credential_id: str | None = None,
) -> RightsPolicyVersion:
    """Return a neutral policy; caller owns commit and integrity publication.

    Registration calls this after flushing the work and before its atomic commit.
    Existing policies are preserved. Registration binds the returned digest into
    its existing WORK_REGISTERED event rather than fabricating a second event.
    """
    if work.deleted_at is not None:
        raise ValueError("Cannot create a rights baseline for a deleted work")
    existing = db.scalar(
        select(RightsPolicyVersion)
        .where(
            RightsPolicyVersion.tenant_id == work.tenant_id,
            RightsPolicyVersion.work_id == work.id,
        )
        .order_by(RightsPolicyVersion.version.desc())
        .limit(1)
    )
    if existing is not None:
        return existing
    payload = RightsPolicyPayload(
        creator_assertion_status="UNKNOWN",
        consent_status="UNKNOWN",
        revocation_status="UNKNOWN",
    )
    row = RightsPolicyVersion(
        tenant_id=work.tenant_id,
        work_id=work.id,
        version=1,
        permissions=payload.normalized_permissions(),
        dimensions=payload.normalized_dimensions(),
        creator_assertions={**payload.assertions(), "baseline_source": UNKNOWN_BASELINE_SOURCE},
        consent_metadata=payload.consent_metadata(),
        revocation_metadata=payload.revocation_metadata(),
        corroboration=[],
        effective_from=utc(work.created_at),
        effective_until=None,
        created_by_principal_id=created_by_principal_id,
    )
    row.digest_sha256 = canonical_digest(policy_integrity_projection(row))
    db.add(row)
    db.flush()
    db.add(
        AuditEvent(
            tenant_id=work.tenant_id,
            principal_id=created_by_principal_id,
            credential_id=credential_id,
            event_type="RIGHTS_POLICY_BASELINE_CREATED",
            resource_type="rights_policy",
            resource_id=row.id,
            attributes={
                "work_id": work.id,
                "version": 1,
                "digest_sha256": row.digest_sha256,
                "baseline_source": UNKNOWN_BASELINE_SOURCE,
            },
        )
    )
    return row
