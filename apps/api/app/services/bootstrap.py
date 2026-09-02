"""Idempotent first-deployment credential bootstrap.

Production disables the published development key, which means a brand-new
database otherwise has no authenticated caller capable of creating the first
stored credential.  An operator-supplied ``cpk_...`` secret can seed exactly one
administrator credential.  Only its prefix and keyed digest are persisted.
"""

from __future__ import annotations

import hmac

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_secret, scopes_for_role, split_presented_key
from app.domain.platform import PrincipalRole
from app.models import ApiCredential


def ensure_bootstrap_credential(
    db: Session,
    *,
    tenant_id: str,
    presented_key: str,
    pepper: str,
    name: str = "Vercel server",
) -> ApiCredential | None:
    """Create or verify the first production credential without exposing it."""
    existing_count = int(
        db.scalar(select(func.count(ApiCredential.id)).where(ApiCredential.tenant_id == tenant_id))
        or 0
    )
    if not presented_key:
        if existing_count:
            return None
        raise RuntimeError(
            "No production API credential exists. Set CREATORPROOF_BOOTSTRAP_API_KEY "
            "for the first deployment."
        )
    split = split_presented_key(presented_key)
    if split is None:
        raise RuntimeError(
            "CREATORPROOF_BOOTSTRAP_API_KEY must use the cpk_<prefix>_<secret> format"
        )
    prefix, secret_part = split
    digest = hash_secret(secret_part, pepper)
    existing = db.scalar(select(ApiCredential).where(ApiCredential.prefix == prefix))
    if existing is not None:
        if existing.tenant_id != tenant_id or not hmac.compare_digest(
            existing.secret_digest, digest
        ):
            raise RuntimeError("CREATORPROOF_BOOTSTRAP_API_KEY conflicts with a stored credential")
        return existing
    if existing_count:
        # Once an operator has created/rotated credentials, changing the bootstrap
        # secret must not silently mint another administrator.
        raise RuntimeError(
            "Stored credentials already exist; remove CREATORPROOF_BOOTSTRAP_API_KEY "
            "or restore its original value."
        )
    role = PrincipalRole.ORG_ADMIN
    credential = ApiCredential(
        tenant_id=tenant_id,
        principal_id=None,
        name=name,
        prefix=prefix,
        secret_digest=digest,
        role=str(role),
        scopes=sorted(scope.value for scope in scopes_for_role(role)),
    )
    db.add(credential)
    db.commit()
    db.refresh(credential)
    return credential
