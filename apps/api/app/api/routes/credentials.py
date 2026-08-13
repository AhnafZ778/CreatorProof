"""API credential administration.

A secret is displayed exactly once. Only the prefix and a keyed digest are stored,
so this endpoint cannot be used to recover an existing key — rotation issues a new
one and links it to its predecessor.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext, generate_api_key, scopes_for_role
from app.domain.platform import AuditEventType, CredentialScope, PrincipalRole
from app.models import ApiCredential
from app.schemas import CredentialCreatedRead, CredentialCreateRequest, CredentialRead
from app.services.audit import record_audit_event

router = APIRouter(prefix="/v1/credentials", tags=["credentials"])


@router.post("", response_model=CredentialCreatedRead, status_code=status.HTTP_201_CREATED)
def create_credential(
    payload: CredentialCreateRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> CredentialCreatedRead:
    role = PrincipalRole(payload.role)
    requested = frozenset(payload.scopes) if payload.scopes else scopes_for_role(role)
    granted = sorted(scope.value for scope in (requested & scopes_for_role(role)))
    if not granted:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "NO_GRANTABLE_SCOPES",
                "message": "The requested scopes are not permitted for this role.",
                "role_scopes": sorted(scope.value for scope in scopes_for_role(role)),
            },
        )
    generated = generate_api_key(container.settings.api_key_pepper)
    credential = ApiCredential(
        tenant_id=auth.tenant_id,
        principal_id=auth.principal_id,
        name=payload.name,
        prefix=generated.prefix,
        secret_digest=generated.digest,
        role=str(role),
        scopes=granted,
        expires_at=(
            datetime.now(UTC) + timedelta(days=payload.expires_in_days)
            if payload.expires_in_days
            else None
        ),
        rotated_from_id=payload.rotates_credential_id,
    )
    db.add(credential)
    if payload.rotates_credential_id:
        previous = db.get(ApiCredential, payload.rotates_credential_id)
        if previous is not None and previous.tenant_id == auth.tenant_id:
            previous.revoked_at = datetime.now(UTC)
    db.commit()
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.CREDENTIAL_CREATED,
        resource_type="api_credential",
        resource_id=credential.id,
        principal_id=auth.principal_id,
        attributes={"role": str(role), "scopes": granted},
    )
    db.refresh(credential)
    return CredentialCreatedRead(
        credential=CredentialRead.model_validate(credential),
        api_key=generated.secret,
    )


@router.get("", response_model=list[CredentialRead])
def list_credentials(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> list[ApiCredential]:
    return list(
        db.scalars(
            select(ApiCredential)
            .where(ApiCredential.tenant_id == auth.tenant_id)
            .order_by(ApiCredential.created_at.desc())
        ).all()
    )


@router.delete("/{credential_id}", response_model=CredentialRead)
def revoke_credential(
    credential_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
) -> ApiCredential:
    credential = db.get(ApiCredential, credential_id)
    if credential is None or credential.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="Credential not found")
    if credential.revoked_at is None:
        credential.revoked_at = datetime.now(UTC)
        db.commit()
        record_audit_event(
            db,
            tenant_id=auth.tenant_id,
            event_type=AuditEventType.CREDENTIAL_REVOKED,
            resource_type="api_credential",
            resource_id=credential.id,
            principal_id=auth.principal_id,
        )
    db.refresh(credential)
    return credential
