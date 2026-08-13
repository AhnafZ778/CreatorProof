"""PostgreSQL RLS session-boundary regression tests.

These tests exercise the transaction lifecycle without requiring a PostgreSQL
server in the default unit suite. The policy itself is migration-tested; here we
verify that every new transaction receives the intended tenant or system setting.
"""

from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api import deps
from app.container import initialize_database
from app.core.security import AuthContext
from app.db import build_database
from app.domain.platform import PrincipalRole
from app.services import tenancy


class _RecordingConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, statement, parameters) -> None:
        self.calls.append((str(statement), parameters))


def test_tenant_context_is_reapplied_after_every_transaction() -> None:
    db = SimpleNamespace(
        info={
            tenancy._TENANT_INFO_KEY: "tn_alpha",
            tenancy._BYPASS_INFO_KEY: False,
        }
    )
    first = _RecordingConnection()
    second = _RecordingConnection()

    tenancy._apply_session_rls_context(db, first)
    # Simulate SQLAlchemy opening the next transaction after a commit.
    tenancy._apply_session_rls_context(db, second)

    expected = [
        ("SELECT set_config('app.tenant_id', :tenant_id, true)", {"tenant_id": "tn_alpha"}),
        ("SELECT set_config('app.bypass_rls', :enabled, true)", {"enabled": "off"}),
    ]
    assert first.calls == expected
    assert second.calls == expected


def test_system_session_keeps_explicit_worker_identity_across_commits(tmp_path) -> None:
    database = build_database(
        SimpleNamespace(database_url=f"sqlite:///{tmp_path / 'rls-system.db'}")
    )
    db = database.system_session()
    try:
        assert db.info[tenancy._BYPASS_INFO_KEY] is True
        db.commit()
        assert db.info[tenancy._BYPASS_INFO_KEY] is True
    finally:
        db.close()


def test_binding_tenant_drops_system_bypass_before_tenant_work(tmp_path) -> None:
    database = build_database(
        SimpleNamespace(database_url=f"sqlite:///{tmp_path / 'rls-transition.db'}")
    )
    db = database.system_session()
    try:
        tenancy.bind_tenant_context(db, "tn_alpha")
        assert db.info[tenancy._TENANT_INFO_KEY] == "tn_alpha"
        assert db.info[tenancy._BYPASS_INFO_KEY] is False
    finally:
        db.close()


def test_authentication_bootstrap_never_grants_request_session_bypass(monkeypatch) -> None:
    lookup_db = MagicMock()
    request_db = MagicMock()
    request_db.info = {}
    database = SimpleNamespace(system_session=MagicMock(return_value=lookup_db))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=SimpleNamespace(database=database))),
        url=SimpleNamespace(path="/v1/works"),
    )
    auth = AuthContext(
        tenant_id="tn_alpha",
        auth_method="api_key",
        role=PrincipalRole.ORG_ADMIN,
        scopes=frozenset(),
    )
    authenticate = MagicMock(return_value=auth)
    bind = MagicMock()
    monkeypatch.setattr(deps, "authenticate", authenticate)
    monkeypatch.setattr(deps, "bind_tenant_context", bind)

    assert deps.get_auth(request, request_db, "cpk_prefix_secret") is auth
    authenticate.assert_called_once_with(request, "cpk_prefix_secret", lookup_db)
    lookup_db.close.assert_called_once_with()
    bind.assert_called_once_with(request_db, "tn_alpha")
    assert tenancy._BYPASS_INFO_KEY not in request_db.info


def test_failed_credential_bootstrap_closes_system_session_and_audits_request_session(
    monkeypatch,
) -> None:
    lookup_db = MagicMock()
    request_db = MagicMock()
    request_db.info = {}
    database = SimpleNamespace(system_session=MagicMock(return_value=lookup_db))
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(container=SimpleNamespace(database=database))),
        url=SimpleNamespace(path="/v1/works"),
    )
    failure = HTTPException(status_code=401, detail="invalid")
    audit = MagicMock()
    monkeypatch.setattr(deps, "authenticate", MagicMock(side_effect=failure))
    monkeypatch.setattr(deps, "record_audit_event", audit)

    with pytest.raises(HTTPException) as caught:
        deps.get_auth(request, request_db, "cpk_prefix_wrong")

    assert caught.value is failure
    lookup_db.close.assert_called_once_with()
    assert audit.call_args.args[0] is request_db


def test_default_policy_seed_binds_its_tenant_before_querying(monkeypatch) -> None:
    events: list[str] = []
    db = MagicMock()
    db.get.return_value = SimpleNamespace(id="tn_dev")
    settings = SimpleNamespace(
        database_url="postgresql+psycopg://not-connected",
        dev_tenant_id="tn_dev",
        dev_tenant_slug="dev",
        enable_postgres_rls=True,
    )
    container = SimpleNamespace(
        settings=settings,
        database=SimpleNamespace(
            system_session=MagicMock(return_value=db),
            assert_runtime_role_safety=MagicMock(),
            startup_lock=MagicMock(return_value=nullcontext()),
        ),
        signer=object(),
        transparency=object(),
        blockchain=object(),
    )
    monkeypatch.setattr(
        "app.container.register_signing_key", lambda *_args: events.append("signing-key")
    )
    monkeypatch.setattr(
        "app.container.bind_tenant_context", lambda *_args: events.append("tenant-bound")
    )
    monkeypatch.setattr(
        "app.container.ensure_default_policy", lambda *_args, **_kwargs: events.append("policy")
    )

    initialize_database(container)

    assert events == ["signing-key", "tenant-bound", "policy"]
    container.database.assert_runtime_role_safety.assert_called_once_with(require_rls=True)
    container.database.system_session.assert_called_once_with()
    db.close.assert_called_once_with()
