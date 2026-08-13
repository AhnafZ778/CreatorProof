"""Tenant context binding for PostgreSQL row-level security.

Every tenant-owned statement runs with ``app.tenant_id`` set on the session. The
RLS policies created by the migration deny reads and writes when the setting is
absent, so a forgotten ``WHERE tenant_id = ...`` cannot silently leak another
organization's catalog.
"""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.observability import set_tenant_context

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")
_SET_BYPASS = text("SELECT set_config('app.bypass_rls', :enabled, true)")

_TENANT_INFO_KEY = "creatorproof.tenant_id"
_BYPASS_INFO_KEY = "creatorproof.bypass_rls"


def _is_postgres(db: Session) -> bool:
    bind = db.get_bind()
    return bool(bind is not None and bind.dialect.name == "postgresql")


def _apply_session_rls_context(db: Session, connection) -> None:
    """Apply the session's intended RLS identity to one database transaction.

    PostgreSQL's ``set_config(..., true)`` is deliberately transaction-local so a
    pooled connection can never retain a previous request's tenant.  A SQLAlchemy
    ``Session`` may span many transactions, however, because every commit starts a
    fresh transaction on the next statement.  Keeping the intended identity in
    ``Session.info`` lets the ``after_begin`` hook below safely restore it after
    every commit.
    """
    if connection.dialect.name != "postgresql":
        return
    if _TENANT_INFO_KEY in db.info:
        connection.execute(
            _SET_TENANT,
            {"tenant_id": str(db.info.get(_TENANT_INFO_KEY) or "")},
        )
    if _BYPASS_INFO_KEY in db.info:
        connection.execute(
            _SET_BYPASS,
            {"enabled": "on" if db.info.get(_BYPASS_INFO_KEY) is True else "off"},
        )


@event.listens_for(Session, "after_begin")
def _restore_rls_context(db: Session, _transaction, connection) -> None:
    _apply_session_rls_context(db, connection)


def bind_tenant_context(db: Session, tenant_id: str | None) -> None:
    """Attach a tenant to this session and all of its future transactions."""
    set_tenant_context(tenant_id)
    db.info[_TENANT_INFO_KEY] = tenant_id or ""
    # Moving a bootstrap/worker session into tenant scope must be a one-way
    # privilege reduction. This also protects a request session if a caller ever
    # accidentally obtains one whose ``info`` dictionary was pre-populated.
    db.info[_BYPASS_INFO_KEY] = False
    if not _is_postgres(db):
        return
    db.execute(_SET_BYPASS, {"enabled": "off"})
    db.execute(_SET_TENANT, {"tenant_id": tenant_id or ""})


def bind_break_glass(db: Session, *, enabled: bool) -> None:
    """Set or clear an administrative override for this session.

    Interactive callers must record an audit event. Internal workers should use
    :func:`bind_system_context`, which makes their cross-tenant responsibility
    explicit at the session-factory boundary.
    """
    db.info[_BYPASS_INFO_KEY] = bool(enabled)
    if not _is_postgres(db):
        return
    db.execute(_SET_BYPASS, {"enabled": "on" if enabled else "off"})


def bind_system_context(db: Session) -> None:
    """Authorize a dedicated internal-worker session for cross-tenant work.

    This must never be used as the request dependency session. It exists for
    global queues, webhook dispatch, recovery, and blockchain receipt workers
    that cannot know a tenant until after claiming a row.
    """
    bind_break_glass(db, enabled=True)


def clear_tenant_context(db: Session) -> None:
    set_tenant_context(None)
    db.info.pop(_TENANT_INFO_KEY, None)
    if _is_postgres(db) and db.in_transaction():
        db.execute(_SET_TENANT, {"tenant_id": ""})
