"""Reviewer case API.

Every action is attributable to a principal or credential and is stored as an
immutable event, so an auditor can reconstruct who decided what and why.
"""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import (
    AuditEventType,
    CredentialScope,
    ReviewCaseState,
    ReviewEventType,
)
from app.models import ReviewCase, Scan
from app.schemas import ReviewActionRequest, ReviewCaseRead
from app.services.audit import record_audit_event
from app.services.blockchain import append_integrity_event, prepare_integrity_event
from app.services.review import (
    case_summary,
    record_review_event,
    transition_allowed,
)

router = APIRouter(prefix="/v1/review-cases", tags=["review"])
logger = logging.getLogger("creatorproof.review")


def _load_case(db: Session, case_id: str, tenant_id: str) -> ReviewCase:
    case = db.get(ReviewCase, case_id)
    if case is None or case.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Review case not found")
    return case


@router.get("", response_model=list[ReviewCaseRead])
def list_cases(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_READ))],
    db: Annotated[Session, Depends(get_db)],
    state: Annotated[ReviewCaseState | None, Query()] = None,
    priority: Annotated[str | None, Query(max_length=20)] = None,
    scan_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ReviewCase]:
    query = select(ReviewCase).where(ReviewCase.tenant_id == auth.tenant_id)
    if state is not None:
        query = query.where(ReviewCase.state == str(state))
    if priority:
        query = query.where(ReviewCase.priority == priority)
    if scan_id:
        query = query.where(ReviewCase.scan_id == scan_id)
    return list(db.scalars(query.order_by(ReviewCase.created_at.desc()).limit(limit)).all())


@router.get("/{case_id}")
def get_case(
    case_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    case = _load_case(db, case_id, auth.tenant_id)
    summary = case_summary(db, case)
    scan = db.get(Scan, case.scan_id)
    if scan is not None:
        packet = scan.evidence_packet or {}
        scope = packet.get("scope") or {}
        # Coverage is surfaced with the case so a reviewer sees what was not checked
        # before they see the recommendation.
        summary["scan"] = {
            "id": scan.id,
            "match_status": scan.match_status,
            "policy_action": scan.policy_action,
            "rights_path": scan.rights_path,
            "reason_codes": list(scan.reason_codes or []),
            "coverage_status": scope.get("coverage_status"),
            "coverage_reason_codes": list(scope.get("coverage_reason_codes") or []),
            "complete_for_declared_catalog": scope.get("complete_for_declared_catalog"),
            "anchor_status": scan.anchor_status,
        }
    return summary


@router.post("/{case_id}/actions", status_code=status.HTTP_201_CREATED)
def append_action(
    case_id: str,
    payload: ReviewActionRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    case = db.scalar(
        select(ReviewCase)
        .where(ReviewCase.id == case_id, ReviewCase.tenant_id == auth.tenant_id)
        .with_for_update()
    )
    if case is None:
        raise HTTPException(status_code=404, detail="Review case not found")
    if payload.state is not None and not transition_allowed(case.state, payload.state):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "INVALID_CASE_TRANSITION",
                "message": f"Cannot move a case from {case.state} to {payload.state}.",
            },
        )
    event_type = ReviewEventType(payload.event_type)
    if event_type == ReviewEventType.DECIDED and payload.disposition is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A decision requires an explicit disposition",
        )

    previous_state = case.state
    previous_disposition = case.disposition
    previous_assignee_principal_id = case.assignee_principal_id
    previous_resolved_at = case.resolved_at
    new_assignee_principal_id = (
        payload.assignee_principal_id
        if payload.assignee_principal_id is not None
        else previous_assignee_principal_id
    )
    new_state = str(payload.state) if payload.state is not None else previous_state
    new_disposition = (
        str(payload.disposition)
        if event_type == ReviewEventType.DECIDED and payload.disposition is not None
        else previous_disposition
    )
    new_resolved_at = previous_resolved_at
    if event_type == ReviewEventType.DECIDED and payload.disposition is not None:
        new_state = str(ReviewCaseState.RESOLVED)
        new_resolved_at = datetime.now(UTC)
    review_event = record_review_event(
        db,
        case=case,
        event_type=event_type,
        actor_label=auth.actor_label,
        actor_principal_id=auth.principal_id,
        note=payload.note,
        disposition=payload.disposition,
        attributes={
            "role": str(auth.role),
            "previous_state": previous_state,
            "new_state": new_state,
            "previous_disposition": previous_disposition,
            "new_disposition": new_disposition,
            "previous_assignee_principal_id": previous_assignee_principal_id,
            "new_assignee_principal_id": new_assignee_principal_id,
        },
    )
    conditions = [
        ReviewCase.id == case.id,
        ReviewCase.tenant_id == auth.tenant_id,
        ReviewCase.state == previous_state,
        ReviewCase.disposition == previous_disposition,
    ]
    conditions.append(
        ReviewCase.assignee_principal_id.is_(None)
        if previous_assignee_principal_id is None
        else ReviewCase.assignee_principal_id == previous_assignee_principal_id
    )
    changed = db.execute(
        update(ReviewCase)
        .where(*conditions)
        .values(
            state=new_state,
            disposition=new_disposition,
            assignee_principal_id=new_assignee_principal_id,
            resolved_at=new_resolved_at,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "STALE_REVIEW_CASE",
                "message": "The review case changed while this action was being recorded.",
                "case_id": case_id,
            },
        )
    db.flush()
    db.refresh(case)
    integrity_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="REVIEW_ACTION_RECORDED",
        subject_type="review_case",
        subject_id=case.id,
        attributes={
            "review_event_id": review_event.id,
            "scan_id": case.scan_id,
            "statement_id": case.statement_id,
            "event_type": str(event_type),
            "previous_state": previous_state,
            "new_state": case.state,
            "previous_disposition": previous_disposition,
            "new_disposition": case.disposition,
            "previous_assignee_principal_id": previous_assignee_principal_id,
            "new_assignee_principal_id": case.assignee_principal_id,
            "actor_principal_id": auth.principal_id,
            "note_sha256": (
                hashlib.sha256(payload.note.encode()).hexdigest() if payload.note else None
            ),
        },
    )
    db.commit()
    try:
        append_integrity_event(
            db,
            event=integrity_event,
            transparency=container.transparency,
            blockchain=container.blockchain,
        )
    except Exception:
        # The signed event committed with the review action. The dispatcher
        # publishes any missing transparency leaf after a transient failure.
        logger.exception("review_integrity_event_publish_deferred event_id=%s", integrity_event.id)

    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.REVIEW_ACTION,
        resource_type="review_case",
        resource_id=case.id,
        principal_id=auth.principal_id,
        credential_id=auth.credential_id,
        correlation_id=case.correlation_id,
        reason=payload.note,
        attributes={"event_type": str(event_type)},
    )
    db.refresh(case)
    return case_summary(db, case)
