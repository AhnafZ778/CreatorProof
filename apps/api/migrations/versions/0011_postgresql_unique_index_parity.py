"""Normalize legacy redundant PostgreSQL unique constraints to ORM indexes.

The baseline created both a column unique constraint and a unique index for a
few identities. SQLAlchemy's unique/index column declaration represents only
the latter. Preserve uniqueness and remove the redundant constraint only when
an independent unique index protects exactly the same columns.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_postgresql_unique_index_parity"
down_revision: str | None = "0010_phase1_schema_contract"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IDENTITIES = (
    ("tenants", "slug"),
    ("api_credentials", "prefix"),
    ("signing_keys", "kid"),
    ("scan_input_bindings", "scan_id"),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column in _IDENTITIES:
        inspector = sa.inspect(op.get_bind())
        indexes = inspector.get_indexes(table)
        protected = any(
            item.get("unique")
            and not item.get("duplicates_constraint")
            and item.get("column_names") == [column]
            for item in indexes
        )
        if not protected:
            raise RuntimeError(f"Refusing to reduce uniqueness protection for {table}.{column}")
        for constraint in inspector.get_unique_constraints(table):
            if constraint.get("column_names") == [column] and constraint.get("name"):
                op.drop_constraint(constraint["name"], table, type_="unique")


def downgrade() -> None:
    # The independent unique indexes still enforce the identical invariant.
    # Restoring duplicate constraints would reintroduce schema drift.
    pass
