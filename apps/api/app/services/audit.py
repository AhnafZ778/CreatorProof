"""Append-only audit trail.

Audit writes must never break the request they describe: a failure to record an
event is logged and swallowed rather than turning a valid operation into a 500.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.domain.platform import AuditEventType
from app.observability import log_event

logger = logging.getLogger("creatorproof.audit")


def record_audit_event(
    db: Session,
    *,
    tenant_id: str | None,
    event_type: AuditEventType,
    resource_type: str | None = None,
    resource_id: str | None = None,
    principal_id: str | None = None,
    credential_id: str | None = None,
    correlation_id: str | None = None,
    reason: str | None = None,
    attributes: dict | None = None,
    commit: bool = True,
) -> None:
    from app.models import AuditEvent

    log_event(
        logger,
        "audit_event",
        event_type=str(event_type),
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
    )
    try:
        db.add(
            AuditEvent(
                tenant_id=tenant_id,
                principal_id=principal_id,
                credential_id=credential_id,
                event_type=str(event_type),
                resource_type=resource_type,
                resource_id=resource_id,
                correlation_id=correlation_id,
                reason=reason,
                attributes=attributes or {},
            )
        )
        if commit:
            db.commit()
    except Exception:
        db.rollback()
        logger.warning("audit_event_persist_failed event_type=%s", event_type)
