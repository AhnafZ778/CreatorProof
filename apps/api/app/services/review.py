"""Reviewer workflow.

A machine result is not a decision. Any ``REVIEW`` or ``SCOPE_INCOMPLETE`` result
opens an accountable case, and every reviewer action is recorded as an immutable,
attributable event.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import MatchStatus, PolicyAction
from app.domain.platform import (
    ReviewCaseState,
    ReviewDisposition,
    ReviewEventType,
)

logger = logging.getLogger("creatorproof.review")

_OPEN_ON_MATCH_STATUS = {str(MatchStatus.SCOPE_INCOMPLETE), str(MatchStatus.ERROR)}
_OPEN_ON_POLICY_ACTION = {str(PolicyAction.REVIEW), str(PolicyAction.BLOCK)}


def case_needed(scan) -> str | None:
    """Return the reason a case is required, or ``None``."""
    if str(scan.policy_action or "") in _OPEN_ON_POLICY_ACTION:
        return f"POLICY_{scan.policy_action}"
    if str(scan.match_status or "") in _OPEN_ON_MATCH_STATUS:
        return f"MATCH_{scan.match_status}"
    return None


def open_review_case_if_needed(
    db: Session,
    scan,
    *,
    statement_id: str | None = None,
    signer=None,
    transparency=None,
    blockchain=None,
):
    """Idempotently open and attest the automatic human-review boundary."""
    from app.models import IntegrityEvent, ReviewCase, ReviewEvent
    from app.services.blockchain import append_integrity_event, prepare_integrity_event

    reason = case_needed(scan)
    if reason is None:
        return None
    existing = db.scalar(
        select(ReviewCase)
        .where(ReviewCase.tenant_id == scan.tenant_id, ReviewCase.scan_id == scan.id)
        .with_for_update()
    )
    created_event = None
    statement_bound_event = None
    if existing is None:
        priority = "HIGH" if str(scan.policy_action) == str(PolicyAction.BLOCK) else "NORMAL"
        case = ReviewCase(
            tenant_id=scan.tenant_id,
            scan_id=scan.id,
            statement_id=statement_id,
            state=ReviewCaseState.OPEN,
            priority=priority,
            opened_reason=reason,
            correlation_id=scan.correlation_id,
        )
        db.add(case)
        db.flush()
        created_event = ReviewEvent(
            tenant_id=scan.tenant_id,
            case_id=case.id,
            event_type=str(ReviewEventType.CREATED),
            actor_label="system",
            note=f"Case opened automatically: {reason}",
            attributes={
                "match_status": scan.match_status,
                "policy_action": scan.policy_action,
                "statement_id": statement_id,
            },
        )
        db.add(created_event)
        db.flush()
    else:
        case = existing
        if case.statement_id is None and statement_id is not None:
            case.statement_id = statement_id
            if signer is not None:
                statement_bound_event = prepare_integrity_event(
                    db,
                    signer=signer,
                    tenant_id=scan.tenant_id,
                    event_type="REVIEW_CASE_STATEMENT_BOUND",
                    subject_type="review_case",
                    subject_id=case.id,
                    attributes={
                        "scan_id": scan.id,
                        "previous_statement_id": None,
                        "new_statement_id": statement_id,
                        "policy_version_id": scan.policy_version_id,
                        "packet_hash_sha256": (
                            ((scan.evidence_packet or {}).get("proof") or {}).get(
                                "packet_hash_sha256"
                            )
                        ),
                    },
                )

    integrity_event = db.scalar(
        select(IntegrityEvent).where(
            IntegrityEvent.tenant_id == scan.tenant_id,
            IntegrityEvent.event_type == "REVIEW_CASE_CREATED",
            IntegrityEvent.subject_type == "review_case",
            IntegrityEvent.subject_id == case.id,
        )
    )
    if integrity_event is None and signer is not None:
        if created_event is None:
            created_event = db.scalar(
                select(ReviewEvent)
                .where(
                    ReviewEvent.tenant_id == scan.tenant_id,
                    ReviewEvent.case_id == case.id,
                    ReviewEvent.event_type == str(ReviewEventType.CREATED),
                )
                .order_by(ReviewEvent.created_at)
                .limit(1)
            )
        integrity_event = prepare_integrity_event(
            db,
            signer=signer,
            tenant_id=scan.tenant_id,
            event_type="REVIEW_CASE_CREATED",
            subject_type="review_case",
            subject_id=case.id,
            attributes={
                "review_event_id": created_event.id if created_event is not None else None,
                "scan_id": scan.id,
                "statement_id": case.statement_id,
                "policy_version_id": scan.policy_version_id,
                "state": case.state,
                "priority": case.priority,
                "opened_reason": case.opened_reason,
                "match_status": scan.match_status,
                "policy_action": scan.policy_action,
                "packet_hash_sha256": ((scan.evidence_packet or {}).get("proof") or {}).get(
                    "packet_hash_sha256"
                ),
            },
        )
    db.commit()
    if transparency is not None:
        for event in (integrity_event, statement_bound_event):
            if event is None:
                continue
            try:
                append_integrity_event(
                    db,
                    event=event,
                    transparency=transparency,
                    blockchain=blockchain,
                )
            except Exception:
                # The signed event and case are already durable. Integrity recovery
                # safely publishes the missing leaf/checkpoint later.
                logger.exception(
                    "review_case_integrity_publish_deferred review_case_id=%s event_id=%s",
                    case.id,
                    event.id,
                )
    return case


def record_review_event(
    db: Session,
    *,
    case,
    event_type: ReviewEventType,
    actor_label: str,
    actor_principal_id: str | None = None,
    note: str | None = None,
    disposition: ReviewDisposition | None = None,
    attributes: dict | None = None,
):
    from app.models import ReviewEvent

    event = ReviewEvent(
        tenant_id=case.tenant_id,
        case_id=case.id,
        event_type=str(event_type),
        actor_principal_id=actor_principal_id,
        actor_label=actor_label,
        note=note,
        disposition=str(disposition) if disposition else None,
        attributes=attributes or {},
    )
    db.add(event)
    return event


_ALLOWED_TRANSITIONS: dict[ReviewCaseState, set[ReviewCaseState]] = {
    ReviewCaseState.OPEN: {
        ReviewCaseState.IN_REVIEW,
        ReviewCaseState.AWAITING_INFORMATION,
        ReviewCaseState.DISPUTED,
        ReviewCaseState.RESOLVED,
        ReviewCaseState.CLOSED,
    },
    ReviewCaseState.IN_REVIEW: {
        ReviewCaseState.AWAITING_INFORMATION,
        ReviewCaseState.DISPUTED,
        ReviewCaseState.RESOLVED,
        ReviewCaseState.CLOSED,
    },
    ReviewCaseState.AWAITING_INFORMATION: {
        ReviewCaseState.IN_REVIEW,
        ReviewCaseState.DISPUTED,
        ReviewCaseState.RESOLVED,
        ReviewCaseState.CLOSED,
    },
    ReviewCaseState.DISPUTED: {
        ReviewCaseState.IN_REVIEW,
        ReviewCaseState.RESOLVED,
        ReviewCaseState.CLOSED,
    },
    ReviewCaseState.RESOLVED: {ReviewCaseState.CLOSED, ReviewCaseState.IN_REVIEW},
    ReviewCaseState.CLOSED: {ReviewCaseState.IN_REVIEW},
}


def transition_allowed(current: str, target: ReviewCaseState) -> bool:
    try:
        return target in _ALLOWED_TRANSITIONS.get(ReviewCaseState(current), set())
    except ValueError:
        return False


def apply_decision(
    db: Session, *, case, disposition: ReviewDisposition, commit: bool = True
) -> None:
    case.disposition = str(disposition)
    case.state = str(ReviewCaseState.RESOLVED)
    case.resolved_at = datetime.now(UTC)
    if commit:
        db.commit()


def case_summary(db: Session, case) -> dict:
    from app.models import ReviewEvent

    events = db.scalars(
        select(ReviewEvent).where(ReviewEvent.case_id == case.id).order_by(ReviewEvent.created_at)
    ).all()
    return {
        "id": case.id,
        "scan_id": case.scan_id,
        "state": case.state,
        "priority": case.priority,
        "disposition": case.disposition,
        "opened_reason": case.opened_reason,
        "assignee_principal_id": case.assignee_principal_id,
        "correlation_id": case.correlation_id,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "resolved_at": case.resolved_at.isoformat() if case.resolved_at else None,
        "events": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor_label": event.actor_label,
                "actor_principal_id": event.actor_principal_id,
                "note": event.note,
                "disposition": event.disposition,
                "attributes": event.attributes,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
        "guidance": [
            "A CreatorProof result is source-scoped evidence and a policy recommendation.",
            "It is not a legal infringement determination and does not establish ownership.",
            "Creator-profile resemblance is advisory and cannot by itself justify a block.",
        ],
    }
