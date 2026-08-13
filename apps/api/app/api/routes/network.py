"""Multi-party attestation network: members and counterparty co-attestations.

CreatorProof's own attestation is signed by CreatorProof, so it cannot show that
anyone else accepted a clearance result. These endpoints let an independent
member sign a decision with its own EVM key and have only the digest of that
decision written to the public chain, bound to the platform attestation.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_any_scope, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.models import CounterpartyAttestation, NetworkMember, Scan
from app.schemas import (
    CoAttestationChallengeRequest,
    CoAttestationSubmitRequest,
    CoAttestationWithdrawRequest,
    NetworkMemberRead,
    NetworkMemberUpsertRequest,
)
from app.services.coattestation import CoAttestationError

router = APIRouter(prefix="/v1/network", tags=["network"])

_NETWORK_READ_SCOPES = (
    CredentialScope.SCANS_READ,
    CredentialScope.RIGHTS_READ,
    CredentialScope.REVIEW_READ,
)


def _service(container: Container):
    service = container.coattestations
    if service is None:  # pragma: no cover - wiring guarantees this
        raise HTTPException(
            status_code=503,
            detail={
                "code": "COUNTERPARTY_ATTESTATION_UNAVAILABLE",
                "message": "The multi-party attestation service is not wired in this process.",
            },
        )
    return service


def _fail(error: CoAttestationError) -> HTTPException:
    return HTTPException(
        status_code=error.http_status,
        detail={"code": error.code, "message": error.message, **error.details},
    )


def _load_scan(db: Session, *, tenant_id: str, scan_id: str) -> Scan:
    scan = db.scalar(select(Scan).where(Scan.tenant_id == tenant_id, Scan.id == scan_id))
    if scan is None:
        raise HTTPException(status_code=404, detail={"code": "SCAN_NOT_FOUND", "id": scan_id})
    return scan


def _load_attestation(
    db: Session, *, tenant_id: str, attestation_id: str
) -> CounterpartyAttestation:
    row = db.scalar(
        select(CounterpartyAttestation).where(
            CounterpartyAttestation.tenant_id == tenant_id,
            CounterpartyAttestation.id == attestation_id,
        )
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "COUNTERPARTY_ATTESTATION_NOT_FOUND", "id": attestation_id},
        )
    return row


@router.get("/status")
def network_status(
    auth: Annotated[AuthContext, Depends(require_any_scope(*_NETWORK_READ_SCOPES))],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Say plainly whether this deployment can accept and anchor co-attestations."""
    del auth
    return {"schema": "creatorproof.network_status.v1", **_service(container).capability()}


@router.put("/members", response_model=NetworkMemberRead, status_code=200)
def upsert_member(
    payload: NetworkMemberUpsertRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> NetworkMember:
    """Record who an address belongs to. Permission still comes from the chain."""
    address = payload.address.lower()
    row = db.scalar(
        select(NetworkMember).where(
            NetworkMember.tenant_id == auth.tenant_id,
            NetworkMember.address == address,
        )
    )
    if row is None:
        row = NetworkMember(tenant_id=auth.tenant_id, address=address)
        db.add(row)
    row.org_id = payload.org_id
    row.display_name = payload.display_name
    row.role = str(payload.role)
    row.status = str(payload.status)
    row.attributes = dict(payload.attributes)
    db.commit()
    db.refresh(row)
    return row


@router.get("/members", response_model=list[NetworkMemberRead])
def list_members(
    auth: Annotated[AuthContext, Depends(require_any_scope(*_NETWORK_READ_SCOPES))],
    db: Annotated[Session, Depends(get_db)],
) -> list[NetworkMember]:
    return list(
        db.scalars(
            select(NetworkMember)
            .where(NetworkMember.tenant_id == auth.tenant_id)
            .order_by(NetworkMember.created_at)
        ).all()
    )


@router.get("/members/{address}")
def member_detail(
    address: str,
    auth: Annotated[AuthContext, Depends(require_any_scope(*_NETWORK_READ_SCOPES))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Resolve a member the way the signature gate does, chain first."""
    try:
        membership = _service(container).resolve_membership(
            db, tenant_id=auth.tenant_id, address=address
        )
    except CoAttestationError as error:
        raise _fail(error) from error
    return {"schema": "creatorproof.network_member_view.v1", **membership}


@router.post("/co-attestations/challenge")
def coattestation_challenge(
    payload: CoAttestationChallengeRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Issue the exact body and typed data the counterparty must sign."""
    scan = _load_scan(db, tenant_id=auth.tenant_id, scan_id=payload.scan_id)
    try:
        return _service(container).challenge(
            db,
            scan=scan,
            signer_address=payload.signer_address,
            party_org_id=payload.party_org_id,
            party_role=str(payload.party_role),
            decision=str(payload.decision),
            decision_note_sha256=payload.decision_note_sha256,
        )
    except CoAttestationError as error:
        raise _fail(error) from error


@router.post("/co-attestations", status_code=201)
def submit_coattestation(
    payload: CoAttestationSubmitRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Verify a counterparty signature and queue its public commitment."""
    scan = _load_scan(db, tenant_id=auth.tenant_id, scan_id=payload.scan_id)
    try:
        return _service(container).record(
            db, scan=scan, body=payload.body, signature=payload.signature
        )
    except CoAttestationError as error:
        raise _fail(error) from error


@router.get("/co-attestations")
def list_coattestations(
    auth: Annotated[AuthContext, Depends(require_any_scope(*_NETWORK_READ_SCOPES))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
    scan_id: Annotated[str | None, Query()] = None,
) -> dict:
    query = select(CounterpartyAttestation).where(
        CounterpartyAttestation.tenant_id == auth.tenant_id
    )
    if scan_id:
        query = query.where(CounterpartyAttestation.scan_id == scan_id)
    rows = list(db.scalars(query.order_by(CounterpartyAttestation.created_at)).all())
    service = _service(container)
    return {
        "schema": "creatorproof.counterparty_attestation_list.v1",
        "scan_id": scan_id,
        "items": [service.describe(db, row) for row in rows],
    }


@router.get("/co-attestations/{attestation_id}")
def coattestation_detail(
    attestation_id: str,
    auth: Annotated[AuthContext, Depends(require_any_scope(*_NETWORK_READ_SCOPES))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    row = _load_attestation(db, tenant_id=auth.tenant_id, attestation_id=attestation_id)
    return _service(container).describe(db, row)


@router.post("/co-attestations/{attestation_id}/withdraw")
def withdraw_coattestation(
    attestation_id: str,
    payload: CoAttestationWithdrawRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Withdraw a commitment going forward. The signed history is not erased."""
    row = _load_attestation(db, tenant_id=auth.tenant_id, attestation_id=attestation_id)
    try:
        return _service(container).withdraw(db, row, reason=payload.reason)
    except CoAttestationError as error:
        raise _fail(error) from error
