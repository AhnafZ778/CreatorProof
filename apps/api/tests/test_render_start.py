from urllib.parse import unquote, urlsplit

import pytest

from scripts.render_start import (
    bootstrap_database,
    psycopg_url,
    runtime_database_url,
    server_command,
    sqlalchemy_url,
)


def test_render_postgres_url_selects_installed_psycopg_driver():
    assert sqlalchemy_url("postgresql://owner:secret@db.internal/app") == (
        "postgresql+psycopg://owner:secret@db.internal/app"
    )
    assert sqlalchemy_url("postgres://owner:secret@db.internal/app") == (
        "postgresql+psycopg://owner:secret@db.internal/app"
    )
    assert psycopg_url("postgresql+psycopg://owner:secret@db.internal/app") == (
        "postgresql://owner:secret@db.internal/app"
    )


def test_runtime_url_preserves_host_database_query_and_encodes_password():
    resolved = runtime_database_url(
        "postgresql://owner:owner-secret@[2001:db8::1]:5433/creatorproof?sslmode=require",
        "creatorproof_app",
        "a p@ss:/?#%",
    )
    parsed = urlsplit(resolved.replace("postgresql+psycopg://", "postgresql://", 1))
    assert parsed.username == "creatorproof_app"
    assert unquote(parsed.password or "") == "a p@ss:/?#%"
    assert parsed.hostname == "2001:db8::1"
    assert parsed.port == 5433
    assert parsed.path == "/creatorproof"
    assert parsed.query == "sslmode=require"


@pytest.mark.parametrize("role", ["CreatorProof", "bad-role", "1bad", "a" * 64])
def test_runtime_url_rejects_unsafe_role_names(role: str):
    with pytest.raises(ValueError, match="safe PostgreSQL role"):
        runtime_database_url("postgresql://owner:p@db/app", role, "secret")


def test_non_migration_start_normalizes_runtime_url_without_owner_secret():
    environment = {
        "CREATORPROOF_RUN_MIGRATIONS_ON_START": "false",
        "CREATORPROOF_DATABASE_URL": "postgresql://app:secret@db/app",
    }
    bootstrap_database(environment)
    assert environment["CREATORPROOF_DATABASE_URL"].startswith("postgresql+psycopg://")
    assert "CREATORPROOF_MIGRATION_DATABASE_URL" not in environment


def test_server_command_honors_render_port_and_uses_one_worker():
    command = server_command({"PORT": "10000"})
    assert command[command.index("--port") + 1] == "10000"
    assert command[command.index("--workers") + 1] == "1"


@pytest.mark.parametrize("port", ["", "0", "65536", "eight-thousand"])
def test_server_command_rejects_invalid_port(port: str):
    with pytest.raises(ValueError, match="PORT"):
        server_command({"PORT": port})
