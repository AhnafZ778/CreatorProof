from collections.abc import Callable, Iterator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.container import Container
from app.core.security import AuthContext, authenticate
from app.domain.platform import AuditEventType, CredentialScope
from app.observability import current_correlation_id
from app.services.audit import record_audit_event
from app.services.tenancy import bind_tenant_context


def get_container(request: Request) -> Container:
    return request.app.state.container


def get_db(request: Request) -> Iterator[Session]:
    container: Container = request.app.state.container
    db = container.database.session_factory()
    try:
        yield db
    finally:
        db.close()


def get_correlation_id() -> str:
    return current_correlation_id()


def get_auth(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AuthContext:
    # The header is declared optional so that its absence is an authentication
    # failure rather than a request-validation error. A caller who forgot the key
    # needs a 401 challenge, not a 422 describing a missing field.
    credential_db: Session | None = None
    try:
        if not x_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "MISSING_API_KEY",
                    "message": "Provide an API key in the X-API-Key header.",
                },
                headers={"WWW-Authenticate": "X-API-Key"},
            )
        # Credential rows are themselves tenant-isolated, but the tenant is not
        # known until the credential has been resolved. Use a short-lived system
        # session only for that bootstrap lookup; the request session never gains
        # cross-tenant privileges.
        container: Container = request.app.state.container
        credential_db = container.database.system_session()
        auth = authenticate(request, x_api_key, credential_db)
    except HTTPException:
        record_audit_event(
            db,
            tenant_id=None,
            event_type=AuditEventType.AUTH_FAILED,
            reason="API key rejected",
            correlation_id=current_correlation_id(),
            attributes={"path": request.url.path},
        )
        raise
    finally:
        if credential_db is not None:
            credential_db.close()
    # Every tenant-owned statement in this request runs with an explicit tenant
    # context. PostgreSQL row-level security denies access when it is absent.
    bind_tenant_context(db, auth.tenant_id)
    return auth


def get_tenant_id(auth: Annotated[AuthContext, Depends(get_auth)]) -> str:
    return auth.tenant_id


def require_scope(scope: CredentialScope) -> Callable[[AuthContext], AuthContext]:
    """Authorize by permission rather than by mere possession of a route."""

    def dependency(auth: Annotated[AuthContext, Depends(get_auth)]) -> AuthContext:
        if not auth.has_scope(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_SCOPE",
                    "message": f"This credential lacks the '{scope.value}' permission.",
                    "required_scope": scope.value,
                },
            )
        return auth

    return dependency


def require_any_scope(*scopes: CredentialScope) -> Callable[[AuthContext], AuthContext]:
    """Authorize inspection surfaces shared by works, rights and scan readers."""

    def dependency(auth: Annotated[AuthContext, Depends(get_auth)]) -> AuthContext:
        if not any(auth.has_scope(scope) for scope in scopes):
            required = [scope.value for scope in scopes]
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "INSUFFICIENT_SCOPE",
                    "message": "This credential lacks a required read permission.",
                    "required_any_scope": required,
                },
            )
        return auth

    return dependency
