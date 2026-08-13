from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError

import app.models  # noqa: F401 - register the complete ORM schema
from app.core.config import Settings
from app.db import _RLS_REQUIRED_TABLES, Base, _runtime_role_safety_problems, build_database

API_ROOT = Path(__file__).resolve().parents[1]


def _production_settings(**overrides) -> Settings:
    values = {
        "environment": "production",
        "database_url": "postgresql+psycopg://creatorproof_app@example.invalid/creatorproof",
        "dev_auth_enabled": False,
        "dev_api_key": "private-nondefault-api-key",
        "api_key_pepper": "private-deployment-pepper",
        "enable_postgres_rls": True,
        "statement_signing_enabled": True,
        "statement_signing_private_key_hex": "11" * 32,
        "trusted_issuer_key_sha256": "22" * 32,
        "proof_anchor_mode": "none",
    }
    values.update(overrides)
    return Settings(**values)


def test_production_accepts_explicit_off_chain_mode_with_real_signing_and_rls() -> None:
    settings = _production_settings()

    assert settings.proof_anchor_mode == "none"
    assert settings.statement_signing_enabled is True
    assert settings.enable_postgres_rls is True


def test_production_rejects_auto_provider_selection() -> None:
    with pytest.raises(ValidationError, match="must be explicit in production"):
        _production_settings(proof_anchor_mode="auto")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"statement_signing_enabled": False}, "SIGNING_ENABLED"),
        ({"statement_signing_private_key_hex": ""}, "SIGNING_PRIVATE_KEY_HEX"),
        ({"enable_postgres_rls": False}, "ENABLE_POSTGRES_RLS"),
    ],
)
def test_production_rejects_unsigned_or_rls_disabled_runtime(overrides, message) -> None:
    with pytest.raises(ValidationError, match=message):
        _production_settings(**overrides)


def test_auto_eas_inputs_require_checkpoint_schema_for_domain_anchoring() -> None:
    with pytest.raises(ValidationError, match="CHECKPOINT_SCHEMA_UID"):
        Settings(
            proof_anchor_mode="auto",
            eas_rpc_url="https://rpc.example.invalid",
            eas_contract_address="0x" + "33" * 20,
            eas_schema_uid="0x" + "44" * 32,
            eas_private_key="0x" + "55" * 32,
            blockchain_domain_anchoring_enabled=True,
        )


def test_runtime_role_safety_rejects_superuser_owner_and_incomplete_rls() -> None:
    table_states = {
        table: {
            "relrowsecurity": True,
            "relforcerowsecurity": True,
            "owned_by_current": False,
        }
        for table in _RLS_REQUIRED_TABLES
    }
    assert (
        _runtime_role_safety_problems(
            {"role_name": "creatorproof_app", "rolsuper": False, "rolbypassrls": False},
            table_states,
        )
        == []
    )

    table_states["works"] = {
        "relrowsecurity": False,
        "relforcerowsecurity": False,
        "owned_by_current": True,
    }
    problems = _runtime_role_safety_problems(
        {"role_name": "creatorproof", "rolsuper": True, "rolbypassrls": True},
        table_states,
    )
    rendered = "; ".join(problems)
    assert "superuser" in rendered
    assert "BYPASSRLS" in rendered
    assert "RLS is not enabled and forced on: works" in rendered
    assert "runtime role owns migration-managed tables" in rendered


@pytest.mark.parametrize("legacy_leaf_constraint", [False, True])
def test_create_all_quickstart_can_be_adopted_by_alembic(
    tmp_path, legacy_leaf_constraint: bool
) -> None:
    database_url = f"sqlite:///{tmp_path / 'create-all-upgrade.db'}"
    database = build_database(Settings(environment="test", database_url=database_url))
    Base.metadata.create_all(database.engine)
    if legacy_leaf_constraint:
        # A short-lived quick-start schema represented replay uniqueness as a
        # UniqueConstraint. Revision 0004 normalizes it without stranding that DB.
        with database.engine.begin() as connection:
            connection.exec_driver_sql("DROP INDEX uq_transparency_leaf_statement")
            operations = Operations(MigrationContext.configure(connection))
            with operations.batch_alter_table("transparency_leaves") as batch_op:
                batch_op.create_unique_constraint(
                    "uq_transparency_leaf_statement", ["log_id", "statement_id"]
                )
    database.engine.dispose()

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    command.check(config)
