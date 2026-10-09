"""Enforce append-only records and attributable human review in SQLite SQL.

Install only after historical backfills. SQLite quick-start installs equivalent
guards after metadata creation; PostgreSQL keeps its existing migration guards.
"""

from collections.abc import Sequence

from alembic import op

from app.sqlite_integrity import SQLITE_IMMUTABLE_TABLES, install_sqlite_integrity_guards

revision: str = "0012_sqlite_database_immutability"
down_revision: str | None = "0011_postgresql_unique_index_parity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    install_sqlite_integrity_guards(op.get_bind())


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    for table in SQLITE_IMMUTABLE_TABLES:
        for operation in ("update", "delete", "insert"):
            op.execute(f'DROP TRIGGER IF EXISTS "{table}_creatorproof_{operation}_guard"')
