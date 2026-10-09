"""Retain user-selected notice context and AI draft provenance."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_user_detection_notice_context"
down_revision: str | None = "0007_marketplace_monitor_and_takedowns"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("takedown_drafts")}
    if "scan_id" not in columns:
        op.add_column("takedown_drafts", sa.Column("scan_id", sa.String(length=64), nullable=True))
    if "generation_provider" not in columns:
        op.add_column(
            "takedown_drafts",
            sa.Column(
                "generation_provider",
                sa.String(length=40),
                nullable=False,
                server_default="template",
            ),
        )
    if "generation_model" not in columns:
        op.add_column(
            "takedown_drafts", sa.Column("generation_model", sa.String(length=160), nullable=True)
        )
    if "marketplace_asset_id" in columns:
        # Existing rows remain valid. PostgreSQL and SQLite both permit this
        # column to be nullable for scan-backed detections; SQLite's existing
        # rows are preserved by the migration layer.
        with op.batch_alter_table("takedown_drafts") as batch:
            batch.alter_column(
                "marketplace_asset_id", existing_type=sa.String(length=64), nullable=True
            )
    indexes = {item.get("name") for item in inspector.get_indexes("takedown_drafts")}
    constraints = {item.get("name") for item in inspector.get_unique_constraints("takedown_drafts")}
    if "ix_takedown_drafts_scan_id" not in indexes | constraints:
        op.create_index("ix_takedown_drafts_scan_id", "takedown_drafts", ["scan_id"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {item.get("name") for item in inspector.get_indexes("takedown_drafts")}
    if "ix_takedown_drafts_scan_id" in indexes:
        op.drop_index("ix_takedown_drafts_scan_id", table_name="takedown_drafts")
    with op.batch_alter_table("takedown_drafts") as batch:
        batch.drop_column("generation_model")
        batch.drop_column("generation_provider")
        batch.drop_column("scan_id")
