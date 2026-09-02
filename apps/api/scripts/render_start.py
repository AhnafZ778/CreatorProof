"""Render-safe database bootstrap followed by the API process.

Render's pre-deploy command is not available to free web services.  This module
therefore performs the minimum privileged work before the HTTP server exists:

1. serialize startup with a PostgreSQL advisory lock;
2. create/update a deliberately unprivileged runtime login;
3. run Alembic as the migration owner and refresh runtime grants;
4. remove owner credentials from the environment; and
5. replace this process with one Uvicorn worker using the runtime login.

No connection URL or password is printed.  Paid deployments should still prefer
Render's separate pre-deploy command, but the same script is safe to use there.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import Mapping, MutableMapping, Sequence
from urllib.parse import quote, urlsplit, urlunsplit

import psycopg
from alembic import command
from psycopg import sql

from scripts.migrate import _config

_STARTUP_MIGRATION_LOCK_ID = 74_148_833_103_175
_ROLE_PATTERN = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def sqlalchemy_url(value: str) -> str:
    """Select SQLAlchemy's installed psycopg v3 driver explicitly."""
    stripped = value.strip()
    if stripped.startswith("postgres://"):
        return "postgresql+psycopg://" + stripped.removeprefix("postgres://")
    if stripped.startswith("postgresql://"):
        return "postgresql+psycopg://" + stripped.removeprefix("postgresql://")
    return stripped


def psycopg_url(value: str) -> str:
    """Convert a SQLAlchemy psycopg URL into a libpq-compatible URL."""
    return value.strip().replace("postgresql+psycopg://", "postgresql://", 1)


def runtime_database_url(owner_url: str, username: str, password: str) -> str:
    """Build a URL for a second login without leaking or double-encoding secrets."""
    if not _ROLE_PATTERN.fullmatch(username):
        raise ValueError("CREATORPROOF_RUNTIME_DATABASE_USER is not a safe PostgreSQL role name")
    if not password:
        raise ValueError("CREATORPROOF_RUNTIME_DATABASE_PASSWORD is required")
    parsed = urlsplit(psycopg_url(owner_url))
    if parsed.scheme != "postgresql" or not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("CREATORPROOF_MIGRATION_DATABASE_URL must be a PostgreSQL URL")
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = f":{parsed.port}" if parsed.port is not None else ""
    credentials = f"{quote(username, safe='')}:{quote(password, safe='')}"
    netloc = f"{credentials}@{host}{port}"
    return sqlalchemy_url(urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, "")))


def _provision_role(connection, *, runtime_user: str, runtime_password: str) -> None:
    if not _ROLE_PATTERN.fullmatch(runtime_user):
        raise ValueError("CREATORPROOF_RUNTIME_DATABASE_USER is not a safe PostgreSQL role name")
    owner, database = connection.execute("SELECT current_user, current_database()").fetchone()
    exists = connection.execute(
        "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s)",
        (runtime_user,),
    ).fetchone()[0]
    if not exists:
        connection.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(runtime_user)))
    connection.execute(
        sql.SQL(
            "ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB "
            "NOCREATEROLE NOREPLICATION NOINHERIT NOBYPASSRLS"
        ).format(sql.Identifier(runtime_user), sql.Literal(runtime_password))
    )
    connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    connection.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(database), sql.Identifier(runtime_user)
        )
    )
    connection.execute(
        sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(runtime_user))
    )
    connection.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
        ).format(sql.Identifier(owner), sql.Identifier(runtime_user))
    )
    connection.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public "
            "GRANT USAGE, SELECT ON SEQUENCES TO {}"
        ).format(sql.Identifier(owner), sql.Identifier(runtime_user))
    )


def _refresh_runtime_grants(connection, *, runtime_user: str) -> None:
    connection.execute(
        sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(
            sql.Identifier(runtime_user)
        )
    )
    connection.execute(
        sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(
            sql.Identifier(runtime_user)
        )
    )


def bootstrap_database(environment: MutableMapping[str, str]) -> None:
    """Prepare PostgreSQL and leave only the runtime URL in ``environment``."""
    owner_url = environment.get("CREATORPROOF_MIGRATION_DATABASE_URL", "").strip()
    run_migrations = environment.get("CREATORPROOF_RUN_MIGRATIONS_ON_START", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not run_migrations:
        runtime_url = environment.get("CREATORPROOF_DATABASE_URL", "").strip()
        if runtime_url:
            environment["CREATORPROOF_DATABASE_URL"] = sqlalchemy_url(runtime_url)
        return
    if not owner_url:
        raise ValueError(
            "CREATORPROOF_MIGRATION_DATABASE_URL is required when migrations run on startup"
        )

    runtime_user = environment.get("CREATORPROOF_RUNTIME_DATABASE_USER", "creatorproof_app")
    runtime_password = environment.get("CREATORPROOF_RUNTIME_DATABASE_PASSWORD", "")
    resolved_runtime_url = runtime_database_url(owner_url, runtime_user, runtime_password)

    # Hold this session-level lock while Alembic uses its own owner connection.
    with psycopg.connect(psycopg_url(owner_url), autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (_STARTUP_MIGRATION_LOCK_ID,))
        try:
            _provision_role(
                connection,
                runtime_user=runtime_user,
                runtime_password=runtime_password,
            )
            command.upgrade(_config(sqlalchemy_url(owner_url)), "head")
            _refresh_runtime_grants(connection, runtime_user=runtime_user)
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (_STARTUP_MIGRATION_LOCK_ID,))

    environment["CREATORPROOF_DATABASE_URL"] = resolved_runtime_url
    # The eventual API process never needs migration authority or the plaintext
    # role password as standalone values.
    environment.pop("CREATORPROOF_MIGRATION_DATABASE_URL", None)
    environment.pop("CREATORPROOF_RUNTIME_DATABASE_PASSWORD", None)


def server_command(environment: Mapping[str, str]) -> list[str]:
    port = environment.get("PORT", "8000")
    if not port.isdigit() or not 1 <= int(port) <= 65_535:
        raise ValueError("PORT must be an integer between 1 and 65535")
    return [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "0.0.0.0",
        "--port",
        port,
        "--workers",
        "1",
        "--proxy-headers",
        "--forwarded-allow-ips",
        "*",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    del argv
    try:
        bootstrap_database(os.environ)
        command_line = server_command(os.environ)
    except Exception as exc:
        # Do not stringify exceptions from connection libraries: their messages
        # can contain connection URLs. The exception class is enough for deploy logs.
        print(f"CreatorProof startup bootstrap failed ({type(exc).__name__}).", file=sys.stderr)
        return 1
    os.execvpe(command_line[0], command_line, os.environ)
    return 0  # pragma: no cover - exec only returns on failure


if __name__ == "__main__":
    raise SystemExit(main())
