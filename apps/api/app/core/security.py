"""Authentication, credential hashing and authorization boundary.

Production credentials are never stored in plaintext. A generated key looks like
``cpk_<prefix>_<secret>``; only ``prefix`` and ``HMAC-SHA256(pepper, secret)`` are
persisted, so a database disclosure does not yield usable keys.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.platform import ROLE_SCOPES, CredentialScope, PrincipalRole

KEY_NAMESPACE = "cpk"
_PREFIX_BYTES = 6
_SECRET_BYTES = 32


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Resolved caller identity. Every tenant-owned query must be filtered by ``tenant_id``."""

    tenant_id: str
    auth_method: str
    role: PrincipalRole
    scopes: frozenset[CredentialScope]
    principal_id: str | None = None
    credential_id: str | None = None
    actor_label: str = "unknown"
    break_glass: bool = False
    attributes: dict = field(default_factory=dict)

    def has_scope(self, scope: CredentialScope) -> bool:
        return CredentialScope.ADMIN in self.scopes or scope in self.scopes


class GeneratedCredential(tuple):
    """(`secret`, `prefix`, `digest`) with named access for readability."""

    __slots__ = ()

    def __new__(cls, secret: str, prefix: str, digest: str) -> GeneratedCredential:
        return super().__new__(cls, (secret, prefix, digest))

    @property
    def secret(self) -> str:
        return self[0]

    @property
    def prefix(self) -> str:
        return self[1]

    @property
    def digest(self) -> str:
        return self[2]


def hash_secret(secret: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), secret.encode("utf-8"), hashlib.sha256).hexdigest()


def generate_api_key(pepper: str) -> GeneratedCredential:
    prefix = secrets.token_hex(_PREFIX_BYTES)
    secret_part = secrets.token_urlsafe(_SECRET_BYTES)
    presented = f"{KEY_NAMESPACE}_{prefix}_{secret_part}"
    return GeneratedCredential(presented, prefix, hash_secret(secret_part, pepper))


def split_presented_key(presented: str) -> tuple[str, str] | None:
    parts = presented.split("_", 2)
    if len(parts) != 3 or parts[0] != KEY_NAMESPACE or not parts[1] or not parts[2]:
        return None
    return parts[1], parts[2]


def scopes_for_role(role: PrincipalRole) -> frozenset[CredentialScope]:
    return ROLE_SCOPES.get(role, frozenset())


def _parse_scopes(raw: list[str] | None, role: PrincipalRole) -> frozenset[CredentialScope]:
    if not raw:
        return scopes_for_role(role)
    resolved: set[CredentialScope] = set()
    for item in raw:
        try:
            resolved.add(CredentialScope(item))
        except ValueError:
            continue
    # A credential can narrow but never widen the permissions granted by its role.
    return frozenset(resolved & scopes_for_role(role)) or frozenset()


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "AUTHENTICATION_FAILED", "message": detail},
        headers={"WWW-Authenticate": "ApiKey"},
    )


def authenticate(request: Request, presented_key: str, db: Session | None = None) -> AuthContext:
    """Resolve an API key into an :class:`AuthContext`.

    Stored credentials are checked first. The development key remains available
    only while ``dev_auth_enabled`` is true, which production configuration refuses.
    """
    container = request.app.state.container
    settings = container.settings

    split = split_presented_key(presented_key)
    if split is not None and db is not None:
        prefix, secret_part = split
        from app.models import ApiCredential

        credential = db.scalar(select(ApiCredential).where(ApiCredential.prefix == prefix))
        if credential is None:
            raise _unauthorized("Unknown API credential")
        expected = hash_secret(secret_part, settings.api_key_pepper)
        if not hmac.compare_digest(expected, credential.secret_digest):
            raise _unauthorized("Invalid API credential")
        now = datetime.now(UTC)
        if credential.revoked_at is not None:
            raise _unauthorized("API credential revoked")
        expires_at = credential.expires_at
        if expires_at is not None:
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at <= now:
                raise _unauthorized("API credential expired")
        credential.last_used_at = now
        db.commit()
        role = PrincipalRole(credential.role)
        return AuthContext(
            tenant_id=credential.tenant_id,
            auth_method="api_key",
            role=role,
            scopes=_parse_scopes(list(credential.scopes or []), role),
            principal_id=credential.principal_id,
            credential_id=credential.id,
            actor_label=credential.name,
        )

    if settings.dev_auth_enabled and secrets.compare_digest(presented_key, settings.dev_api_key):
        role = PrincipalRole.ORG_ADMIN
        return AuthContext(
            tenant_id=settings.dev_tenant_id,
            auth_method="development_key",
            role=role,
            scopes=scopes_for_role(role),
            actor_label="development-key",
            attributes={
                "warning": "DEVELOPMENT_CREDENTIAL_NOT_A_PRODUCTION_SECURITY_BOUNDARY",
            },
        )

    raise _unauthorized("Invalid API key")


def require_tenant(request: Request, x_api_key: str) -> str:
    """Backwards-compatible helper retained for v1 call sites."""
    return authenticate(request, x_api_key).tenant_id
