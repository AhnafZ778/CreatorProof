"""Rights domain API: parties, claims, licenses and their lifecycle events.

Corroboration, dispute, supersession, revocation and expiry are recorded as
append-only events. A terminal state removes authorization for future decisions
and never edits a decision that was already made.
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
from app.domain.enums import ClaimState
from app.domain.platform import AuditEventType, CredentialScope, LicenseState, RightsEventType
from app.models import Claim, License, Party, RightsEvent, Work
from app.schemas import (
    ClaimCreateRequest,
    ClaimRead,
    LicenseCreateRequest,
    LicenseRead,
    PartyCreateRequest,
    PartyRead,
    RightsEventRequest,
)
from app.services.audit import record_audit_event
from app.services.blockchain import append_integrity_event, prepare_integrity_event
from app.services.canonical import canonical_digest
from app.services.policy_store import claim_integrity_projection, license_integrity_projection

router = APIRouter(prefix="/v1/rights", tags=["rights"])
logger = logging.getLogger("creatorproof.rights")


def _sha256_text(value: str | None) -> str | None:
    return hashlib.sha256(value.encode()).hexdigest() if value else None


def _state_conflict(*, subject: str, current_state: str, event_type: RightsEventType) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "INVALID_RIGHTS_STATE_TRANSITION",
            "message": f"{event_type} cannot follow {current_state} for this {subject}.",
            "subject_type": subject,
            "current_state": current_state,
            "event_type": str(event_type),
        },
    )


def _publish_integrity_event(db: Session, container: Container, event) -> None:
    try:
        append_integrity_event(
            db,
            event=event,
            transparency=container.transparency,
            blockchain=container.blockchain,
        )
    except Exception:
        # The event itself committed with the rights mutation. The dispatcher
        # finds signed events without leaves and safely resumes publication.
        logger.exception("rights_integrity_event_publish_deferred event_id=%s", event.id)


def _projection_attributes(projection: dict) -> dict:
    return {
        "projection": projection,
        "projection_digest_sha256": canonical_digest(projection),
    }


def _concurrent_transition(subject: str, subject_id: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "STALE_RIGHTS_PROJECTION",
            "message": f"The {subject} changed while this transition was being recorded.",
            "subject_type": subject,
            "subject_id": subject_id,
        },
    )


_CLAIM_EVENT_STATES = {
    RightsEventType.CORROBORATED: ClaimState.CORROBORATED,
    RightsEventType.DISPUTED: ClaimState.DISPUTED,
    RightsEventType.SUPERSEDED: ClaimState.SUPERSEDED,
    RightsEventType.REVOKED: ClaimState.REVOKED,
}

_LICENSE_EVENT_STATES = {
    RightsEventType.DISPUTED: LicenseState.SUSPENDED,
    RightsEventType.SUPERSEDED: LicenseState.SUPERSEDED,
    RightsEventType.REVOKED: LicenseState.REVOKED,
    RightsEventType.EXPIRED: LicenseState.EXPIRED,
}

_CLAIM_TRANSITIONS = {
    ClaimState.ASSERTED: frozenset(
        {
            RightsEventType.CORROBORATED,
            RightsEventType.DISPUTED,
            RightsEventType.SUPERSEDED,
            RightsEventType.REVOKED,
        }
    ),
    ClaimState.CORROBORATED: frozenset(
        {RightsEventType.DISPUTED, RightsEventType.SUPERSEDED, RightsEventType.REVOKED}
    ),
    ClaimState.DISPUTED: frozenset(
        {RightsEventType.CORROBORATED, RightsEventType.SUPERSEDED, RightsEventType.REVOKED}
    ),
    ClaimState.SUPERSEDED: frozenset(),
    ClaimState.REVOKED: frozenset(),
}

_LICENSE_TRANSITIONS = {
    LicenseState.ACTIVE: frozenset(
        {
            RightsEventType.DISPUTED,
            RightsEventType.SUPERSEDED,
            RightsEventType.REVOKED,
            RightsEventType.EXPIRED,
        }
    ),
    LicenseState.SUSPENDED: frozenset(
        {RightsEventType.SUPERSEDED, RightsEventType.REVOKED, RightsEventType.EXPIRED}
    ),
    LicenseState.SUPERSEDED: frozenset(),
    LicenseState.REVOKED: frozenset(),
    LicenseState.EXPIRED: frozenset(),
}


def _require_work(db: Session, tenant_id: str, work_id: str) -> Work:
    work = db.get(Work, work_id)
    if work is None or work.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Work not found")
    return work


def _require_party(db: Session, tenant_id: str, party_id: str | None) -> Party | None:
    if party_id is None:
        return None
    party = db.get(Party, party_id)
    if party is None or party.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Claimant party not found")
    return party


def _require_claim_for_license(
    db: Session, *, tenant_id: str, work_id: str, claim_id: str | None
) -> Claim | None:
    if claim_id is None:
        return None
    claim = db.get(Claim, claim_id)
    if claim is None or claim.tenant_id != tenant_id or claim.work_id != work_id:
        raise HTTPException(status_code=404, detail="Claim not found for this work")
    if ClaimState(claim.state) in {ClaimState.DISPUTED, ClaimState.SUPERSEDED, ClaimState.REVOKED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "LICENSE_REFERENCES_INACTIVE_CLAIM",
                "message": "A disputed, superseded or revoked claim cannot back a new license.",
                "claim_id": claim.id,
                "claim_state": claim.state,
            },
        )
    return claim


def _validate_supersession_target(
    db: Session,
    *,
    tenant_id: str,
    subject,
    event_type: RightsEventType,
    superseded_by_id: str | None,
):
    if event_type != RightsEventType.SUPERSEDED:
        if superseded_by_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="superseded_by_id is valid only for a SUPERSEDED event",
            )
        return None
    if not superseded_by_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A SUPERSEDED event requires superseded_by_id",
        )
    if superseded_by_id == subject.id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A rights record cannot supersede itself",
        )
    replacement = db.get(type(subject), superseded_by_id)
    if (
        replacement is None
        or replacement.tenant_id != tenant_id
        or replacement.work_id != subject.work_id
    ):
        raise HTTPException(status_code=404, detail="Superseding record not found for this work")
    return replacement


@router.post("/parties", response_model=PartyRead, status_code=status.HTTP_201_CREATED)
def create_party(
    payload: PartyCreateRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> Party:
    existing = db.scalar(
        select(Party).where(
            Party.tenant_id == auth.tenant_id, Party.external_ref == payload.external_ref
        )
    )
    if existing is not None:
        return existing
    party = Party(
        tenant_id=auth.tenant_id,
        external_ref=payload.external_ref,
        display_name=payload.display_name,
        party_type=payload.party_type,
    )
    db.add(party)
    db.flush()
    integrity_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="PARTY_CREATED",
        subject_type="party",
        subject_id=party.id,
        attributes={
            "external_ref_sha256": _sha256_text(party.external_ref),
            "display_name_sha256": _sha256_text(party.display_name),
            "party_type": party.party_type,
        },
    )
    db.commit()
    _publish_integrity_event(db, container, integrity_event)
    db.refresh(party)
    return party


@router.get("/parties", response_model=list[PartyRead])
def list_parties(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> list[Party]:
    return list(
        db.scalars(
            select(Party).where(Party.tenant_id == auth.tenant_id).order_by(Party.created_at)
        ).all()
    )


@router.post("/claims", response_model=ClaimRead, status_code=status.HTTP_201_CREATED)
def create_claim(
    payload: ClaimCreateRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> Claim:
    """Record an asserted claim.

    A new claim always starts as ``ASSERTED``. Corroboration is a separate,
    evidenced event; it is never granted by the act of claiming.
    """
    _require_work(db, auth.tenant_id, payload.work_id)
    _require_party(db, auth.tenant_id, payload.claimant_party_id)
    claim = Claim(
        tenant_id=auth.tenant_id,
        work_id=payload.work_id,
        claimant_party_id=payload.claimant_party_id,
        claimant_label=payload.claimant_label,
        claim_type=payload.claim_type,
        state=str(ClaimState.ASSERTED),
        authority_level=payload.authority_level,
        evidence_uri=payload.evidence_uri,
        effective_from=datetime.now(UTC),
    )
    db.add(claim)
    db.flush()
    projection = claim_integrity_projection(claim)
    integrity_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="CLAIM_CREATED",
        subject_type="claim",
        subject_id=claim.id,
        attributes={
            "work_id": claim.work_id,
            "claimant_party_id": claim.claimant_party_id,
            "claimant_label_sha256": _sha256_text(claim.claimant_label),
            "claim_type": claim.claim_type,
            "state": claim.state,
            "authority_level": claim.authority_level,
            "evidence_uri_sha256": _sha256_text(claim.evidence_uri),
            "version": claim.version,
            "assertion_only": True,
            **_projection_attributes(projection),
        },
    )
    db.commit()
    _publish_integrity_event(db, container, integrity_event)
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.RIGHTS_CHANGED,
        resource_type="claim",
        resource_id=claim.id,
        principal_id=auth.principal_id,
        reason="claim created",
    )
    db.refresh(claim)
    return claim


@router.get("/claims", response_model=list[ClaimRead])
def list_claims(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
    work_id: Annotated[str | None, Query()] = None,
) -> list[Claim]:
    query = select(Claim).where(Claim.tenant_id == auth.tenant_id)
    if work_id:
        query = query.where(Claim.work_id == work_id)
    return list(db.scalars(query.order_by(Claim.created_at)).all())


@router.post("/claims/{claim_id}/events", response_model=ClaimRead)
def append_claim_event(
    claim_id: str,
    payload: RightsEventRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> Claim:
    claim = db.scalar(
        select(Claim)
        .where(Claim.id == claim_id, Claim.tenant_id == auth.tenant_id)
        .with_for_update()
    )
    if claim is None or claim.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="Claim not found")
    event_type = RightsEventType(payload.event_type)
    target_state = _CLAIM_EVENT_STATES.get(event_type)
    if target_state is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="EXPIRED does not apply to claims",
        )
    current_state = ClaimState(claim.state)
    if event_type not in _CLAIM_TRANSITIONS[current_state]:
        _state_conflict(
            subject="claim",
            current_state=str(current_state),
            event_type=event_type,
        )
    replacement = _validate_supersession_target(
        db,
        tenant_id=auth.tenant_id,
        subject=claim,
        event_type=event_type,
        superseded_by_id=payload.superseded_by_id,
    )
    previous_state = claim.state
    previous_version = claim.version
    next_version = previous_version + 1
    effective_until = claim.effective_until
    if target_state in {ClaimState.REVOKED, ClaimState.SUPERSEDED}:
        effective_until = datetime.now(UTC)
    rights_event = RightsEvent(
        tenant_id=auth.tenant_id,
        subject_type="claim",
        subject_id=claim.id,
        event_type=str(event_type),
        actor_principal_id=auth.principal_id,
        reason=payload.reason,
        evidence_uri=payload.evidence_uri,
        attributes={
            "previous_state": previous_state,
            "new_state": str(target_state),
            "previous_version": previous_version,
            "version": next_version,
            "superseded_by_id": replacement.id if replacement else None,
        },
    )
    db.add(rights_event)
    changed = db.execute(
        update(Claim)
        .where(
            Claim.id == claim.id,
            Claim.tenant_id == auth.tenant_id,
            Claim.state == previous_state,
            Claim.version == previous_version,
        )
        .values(
            state=str(target_state),
            version=next_version,
            superseded_by_id=replacement.id if replacement else None,
            effective_until=effective_until,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        _concurrent_transition("claim", claim_id)
    db.flush()
    db.refresh(claim)
    projection = claim_integrity_projection(claim)
    integrity_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="CLAIM_STATE_CHANGED",
        subject_type="claim",
        subject_id=claim.id,
        attributes={
            "rights_event_id": rights_event.id,
            "work_id": claim.work_id,
            "event_type": str(event_type),
            "previous_state": previous_state,
            "new_state": claim.state,
            "version": claim.version,
            "superseded_by_id": claim.superseded_by_id,
            "actor_principal_id": auth.principal_id,
            "reason_sha256": _sha256_text(payload.reason),
            "evidence_uri_sha256": _sha256_text(payload.evidence_uri),
            **_projection_attributes(projection),
        },
    )
    db.commit()
    _publish_integrity_event(db, container, integrity_event)
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.RIGHTS_CHANGED,
        resource_type="claim",
        resource_id=claim.id,
        principal_id=auth.principal_id,
        reason=payload.reason,
        attributes={"event_type": str(event_type)},
    )
    db.refresh(claim)
    return claim


@router.post("/licenses", response_model=LicenseRead, status_code=status.HTTP_201_CREATED)
def create_license(
    payload: LicenseCreateRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> License:
    _require_work(db, auth.tenant_id, payload.work_id)
    _require_claim_for_license(
        db,
        tenant_id=auth.tenant_id,
        work_id=payload.work_id,
        claim_id=payload.claim_id,
    )
    effective_from = payload.effective_from or datetime.now(UTC)
    effective_from = (
        effective_from.replace(tzinfo=UTC)
        if effective_from.tzinfo is None
        else effective_from.astimezone(UTC)
    )
    effective_until = payload.effective_until
    if effective_until is not None:
        effective_until = (
            effective_until.replace(tzinfo=UTC)
            if effective_until.tzinfo is None
            else effective_until.astimezone(UTC)
        )
        start = effective_from
        end = effective_until
        if end <= start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="effective_until must be later than effective_from",
            )
    overlap = sorted(set(payload.permitted_uses) & set(payload.prohibited_uses))
    if overlap:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "CONTRADICTORY_LICENSE_SCOPE",
                "message": "A use cannot be both permitted and prohibited.",
                "uses": overlap,
            },
        )
    latest = db.scalar(
        select(License)
        .where(License.tenant_id == auth.tenant_id, License.work_id == payload.work_id)
        .order_by(License.version.desc())
        .limit(1)
    )
    license_row = License(
        tenant_id=auth.tenant_id,
        work_id=payload.work_id,
        claim_id=payload.claim_id,
        version=(latest.version + 1) if latest is not None else 1,
        state=str(LicenseState.ACTIVE),
        permitted_uses=payload.permitted_uses,
        prohibited_uses=payload.prohibited_uses,
        territories=payload.territories,
        channels=payload.channels,
        audiences=payload.audiences,
        transformations=payload.transformations,
        duties=payload.duties,
        effective_from=effective_from,
        effective_until=effective_until,
        source_uri=payload.source_uri,
    )
    db.add(license_row)
    db.flush()
    projection = license_integrity_projection(license_row)
    integrity_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="LICENSE_CREATED",
        subject_type="license",
        subject_id=license_row.id,
        attributes={
            "work_id": license_row.work_id,
            "claim_id": license_row.claim_id,
            "version": license_row.version,
            "state": license_row.state,
            "permitted_uses": license_row.permitted_uses,
            "prohibited_uses": license_row.prohibited_uses,
            "territories": license_row.territories,
            "channels": license_row.channels,
            "audiences": license_row.audiences,
            "transformations": license_row.transformations,
            "duties": license_row.duties,
            "effective_from": license_row.effective_from.isoformat()
            if license_row.effective_from
            else None,
            "effective_until": license_row.effective_until.isoformat()
            if license_row.effective_until
            else None,
            "source_uri_sha256": _sha256_text(license_row.source_uri),
            **_projection_attributes(projection),
        },
    )
    db.commit()
    _publish_integrity_event(db, container, integrity_event)
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.RIGHTS_CHANGED,
        resource_type="license",
        resource_id=license_row.id,
        principal_id=auth.principal_id,
        reason="license recorded",
    )
    db.refresh(license_row)
    return license_row


@router.get("/licenses", response_model=list[LicenseRead])
def list_licenses(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
    work_id: Annotated[str | None, Query()] = None,
) -> list[License]:
    query = select(License).where(License.tenant_id == auth.tenant_id)
    if work_id:
        query = query.where(License.work_id == work_id)
    return list(db.scalars(query.order_by(License.created_at)).all())


@router.post("/licenses/{license_id}/events", response_model=LicenseRead)
def append_license_event(
    license_id: str,
    payload: RightsEventRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> License:
    license_row = db.scalar(
        select(License)
        .where(License.id == license_id, License.tenant_id == auth.tenant_id)
        .with_for_update()
    )
    if license_row is None or license_row.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="License not found")
    event_type = RightsEventType(payload.event_type)
    target_state = _LICENSE_EVENT_STATES.get(event_type)
    if target_state is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="CORROBORATED does not apply to licenses",
        )
    current_state = LicenseState(license_row.state)
    if event_type not in _LICENSE_TRANSITIONS[current_state]:
        _state_conflict(
            subject="license",
            current_state=str(current_state),
            event_type=event_type,
        )
    replacement = _validate_supersession_target(
        db,
        tenant_id=auth.tenant_id,
        subject=license_row,
        event_type=event_type,
        superseded_by_id=payload.superseded_by_id,
    )
    previous_state = license_row.state
    previous_version = license_row.version
    next_version = previous_version + 1
    effective_until = license_row.effective_until
    if target_state in {LicenseState.EXPIRED, LicenseState.REVOKED, LicenseState.SUPERSEDED}:
        effective_until = datetime.now(UTC)
    rights_event = RightsEvent(
        tenant_id=auth.tenant_id,
        subject_type="license",
        subject_id=license_row.id,
        event_type=str(event_type),
        actor_principal_id=auth.principal_id,
        reason=payload.reason,
        evidence_uri=payload.evidence_uri,
        attributes={
            "previous_state": previous_state,
            "new_state": str(target_state),
            "previous_version": previous_version,
            "version": next_version,
            "superseded_by_id": replacement.id if replacement else None,
        },
    )
    db.add(rights_event)
    changed = db.execute(
        update(License)
        .where(
            License.id == license_row.id,
            License.tenant_id == auth.tenant_id,
            License.state == previous_state,
            License.version == previous_version,
        )
        .values(
            state=str(target_state),
            version=next_version,
            superseded_by_id=replacement.id if replacement else None,
            effective_until=effective_until,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        _concurrent_transition("license", license_id)
    db.flush()
    db.refresh(license_row)
    projection = license_integrity_projection(license_row)
    integrity_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="LICENSE_STATE_CHANGED",
        subject_type="license",
        subject_id=license_row.id,
        attributes={
            "rights_event_id": rights_event.id,
            "work_id": license_row.work_id,
            "event_type": str(event_type),
            "previous_state": previous_state,
            "new_state": license_row.state,
            "version": license_row.version,
            "superseded_by_id": license_row.superseded_by_id,
            "actor_principal_id": auth.principal_id,
            "reason_sha256": _sha256_text(payload.reason),
            "evidence_uri_sha256": _sha256_text(payload.evidence_uri),
            **_projection_attributes(projection),
        },
    )
    db.commit()
    _publish_integrity_event(db, container, integrity_event)
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.RIGHTS_CHANGED,
        resource_type="license",
        resource_id=license_row.id,
        principal_id=auth.principal_id,
        reason=payload.reason,
        attributes={"event_type": str(event_type)},
    )
    db.refresh(license_row)
    return license_row


@router.get("/works/{work_id}/position")
def rights_position(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
    intended_use: Annotated[str, Query(min_length=1, max_length=160)] = "review",
) -> dict:
    """Reviewer-safe summary of what is and is not authorized, and what is missing."""
    from app.services.policy_store import collect_rights_facts

    _require_work(db, auth.tenant_id, work_id)
    facts = collect_rights_facts(
        db, tenant_id=auth.tenant_id, work_id=work_id, intended_use=intended_use
    )
    # Claim and licence events are recorded against their own subject, so a query
    # restricted to the work id would show an empty history exactly when a reviewer
    # needs to see that a claim was revoked or a licence expired.
    subject_ids = {work_id}
    subject_ids.update(
        db.scalars(
            select(Claim.id).where(Claim.tenant_id == auth.tenant_id, Claim.work_id == work_id)
        )
    )
    subject_ids.update(
        db.scalars(
            select(License.id).where(
                License.tenant_id == auth.tenant_id, License.work_id == work_id
            )
        )
    )
    events = db.scalars(
        select(RightsEvent)
        .where(
            RightsEvent.tenant_id == auth.tenant_id,
            RightsEvent.subject_id.in_(subject_ids),
        )
        .order_by(RightsEvent.created_at)
    ).all()
    return {
        **facts,
        "intended_use": intended_use,
        "history": [
            {
                "event_type": event.event_type,
                "subject_type": event.subject_type,
                "subject_id": event.subject_id,
                "reason": event.reason,
                "created_at": event.created_at.isoformat() if event.created_at else None,
            }
            for event in events
        ],
        "notes": [
            "A recorded claim is an assertion, not a verified legal ownership finding.",
            "A revoked, disputed, superseded or expired record cannot authorize a use.",
        ],
    }
