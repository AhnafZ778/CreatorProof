"""Record what the enrollment AI-origin gate concluded about each registered work.

Nullable on purpose: a work registered before this column existed, or while the
gate was switched off, has no verdict, and that is not the same as a work that
was screened and came back quiet.

Revision ID: 0006_registration_origin_gate
Revises: 0005_multiparty_attestation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_registration_origin_gate"
down_revision: str | None = "0005_multiparty_attestation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return column_name in {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if not _has_column("works", "origin_assessment"):
        op.add_column("works", sa.Column("origin_assessment", sa.JSON(), nullable=True))


def downgrade() -> None:
    if _has_column("works", "origin_assessment"):
        op.drop_column("works", "origin_assessment")
