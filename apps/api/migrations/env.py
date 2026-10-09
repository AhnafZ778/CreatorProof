"""Alembic environment.

The database URL always comes from application settings, so a migration cannot be
run against a different database than the one the service will use.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from alembic.ddl.postgresql import PostgresqlImpl
from sqlalchemy import String, engine_from_config, inspect, pool

from app.core.config import Settings
from app.db import Base
from app.models import *  # noqa: F401,F403 - import side effect registers every table

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


class CreatorProofPostgresqlImpl(PostgresqlImpl):
    """Keep descriptive revision identifiers within the PostgreSQL column size.

    Alembic defaults to VARCHAR(32). Existing CreatorProof revision identifiers
    are longer; SQLite silently accepts them but PostgreSQL correctly rejects
    the version update. Use Alembic's version-table hook for both online and
    offline fresh schemas, without renaming deployed revision identities.
    """

    __dialect__ = "postgresql"

    def version_table_impl(self, **kwargs):
        table = super().version_table_impl(**kwargs)
        table.c.version_num.type = String(128)
        return table


def _ensure_version_table_capacity(connection) -> None:
    if connection.dialect.name != "postgresql":
        return
    inspector = inspect(connection)
    if not inspector.has_table("alembic_version"):
        return
    columns = inspector.get_columns("alembic_version")
    version_column = next(item for item in columns if item["name"] == "version_num")
    length = getattr(version_column["type"], "length", None)
    if length is not None and length < 128:
        connection.exec_driver_sql(
            "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"
        )


def _database_url() -> str:
    override = config.get_main_option("sqlalchemy.url")
    if override:
        return override
    return Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            _ensure_version_table_capacity(connection)
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
