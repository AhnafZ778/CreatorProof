import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.security import hash_secret
from app.db import Base
from app.models import ApiCredential, Tenant
from app.services.bootstrap import ensure_bootstrap_credential


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(Tenant(id="tn_demo", slug="demo", name="Demo"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def test_bootstrap_credential_is_hashed_and_idempotent(db):
    key = "cpk_a1b2c3d4e5f6_a-very-private-secret"
    created = ensure_bootstrap_credential(
        db,
        tenant_id="tn_demo",
        presented_key=key,
        pepper="private-pepper",
    )
    assert created is not None
    assert created.prefix == "a1b2c3d4e5f6"
    assert created.secret_digest == hash_secret("a-very-private-secret", "private-pepper")
    assert key not in created.secret_digest

    again = ensure_bootstrap_credential(
        db,
        tenant_id="tn_demo",
        presented_key=key,
        pepper="private-pepper",
    )
    assert again is not None
    assert again.id == created.id
    assert db.query(ApiCredential).count() == 1


def test_bootstrap_requires_key_only_for_an_empty_tenant(db):
    with pytest.raises(RuntimeError, match="No production API credential"):
        ensure_bootstrap_credential(
            db,
            tenant_id="tn_demo",
            presented_key="",
            pepper="private-pepper",
        )

    ensure_bootstrap_credential(
        db,
        tenant_id="tn_demo",
        presented_key="cpk_abcdef123456_initial-secret",
        pepper="private-pepper",
    )
    assert (
        ensure_bootstrap_credential(
            db,
            tenant_id="tn_demo",
            presented_key="",
            pepper="private-pepper",
        )
        is None
    )


def test_bootstrap_refuses_changed_admin_secret_after_initialization(db):
    ensure_bootstrap_credential(
        db,
        tenant_id="tn_demo",
        presented_key="cpk_abcdef123456_initial-secret",
        pepper="private-pepper",
    )
    with pytest.raises(RuntimeError, match="Stored credentials already exist"):
        ensure_bootstrap_credential(
            db,
            tenant_id="tn_demo",
            presented_key="cpk_999999999999_replacement-secret",
            pepper="private-pepper",
        )
