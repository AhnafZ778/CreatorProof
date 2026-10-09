"""Durable marketplace monitoring history and reviewable takedown drafts.

Revision ID: 0007_marketplace_monitor_and_takedowns
Revises: 0006_registration_origin_gate
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_marketplace_monitor_and_takedowns"
down_revision: str | None = "0006_registration_origin_gate"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _enable_tenant_isolation(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
        USING (tenant_id = current_setting('app.tenant_id', true)
               OR current_setting('app.bypass_rls', true) = 'on')
        WITH CHECK (tenant_id = current_setting('app.tenant_id', true)
                    OR current_setting('app.bypass_rls', true) = 'on')
        """
    )


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item.get("name") for item in inspector.get_indexes(table)}
    existing |= {item.get("name") for item in inspector.get_unique_constraints(table)}
    if name not in existing:
        op.create_index(name, table, columns)


def upgrade() -> None:
    if not _table_exists("marketplace_assets"):
        op.create_table(
            "marketplace_assets",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("provider", sa.String(length=24), nullable=False),
            sa.Column("external_id", sa.String(length=100), nullable=False),
            sa.Column("title", sa.String(length=240), nullable=False),
            sa.Column("source_url", sa.String(length=512), nullable=False),
            sa.Column("image_url", sa.String(length=1024), nullable=False),
            sa.Column("thumbnail_url", sa.String(length=1024), nullable=True),
            sa.Column("creator", sa.String(length=240), nullable=True),
            sa.Column("width", sa.Integer(), nullable=True),
            sa.Column("height", sa.Integer(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False),
            sa.Column("observation_id", sa.String(length=64), nullable=True),
            sa.Column("scan_id", sa.String(length=64), nullable=True),
            sa.Column("classification", sa.String(length=40), nullable=False),
            sa.Column("country_code", sa.String(length=2), nullable=True),
            sa.Column("jurisdiction_basis", sa.String(length=240), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id", "provider", "external_id", name="uq_marketplace_asset_source"
            ),
        )
    _create_index_if_missing(
        "ix_marketplace_asset_tenant_seen", "marketplace_assets", ["tenant_id", "last_seen_at"]
    )
    _create_index_if_missing(
        "ix_marketplace_asset_classification", "marketplace_assets", ["tenant_id", "classification"]
    )
    _create_index_if_missing("ix_marketplace_assets_tenant_id", "marketplace_assets", ["tenant_id"])
    _create_index_if_missing("ix_marketplace_assets_scan_id", "marketplace_assets", ["scan_id"])
    if not _table_exists("takedown_drafts"):
        op.create_table(
            "takedown_drafts",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("marketplace_asset_id", sa.String(length=64), nullable=False),
            sa.Column("jurisdiction", sa.String(length=40), nullable=False),
            sa.Column("recipient_email", sa.String(length=320), nullable=True),
            sa.Column("recipient_country_code", sa.String(length=2), nullable=True),
            sa.Column("subject", sa.String(length=320), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("state", sa.String(length=32), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "ix_takedown_draft_tenant_created", "takedown_drafts", ["tenant_id", "created_at"]
    )
    _create_index_if_missing("ix_takedown_drafts_tenant_id", "takedown_drafts", ["tenant_id"])
    _create_index_if_missing(
        "ix_takedown_drafts_marketplace_asset_id", "takedown_drafts", ["marketplace_asset_id"]
    )
    _enable_tenant_isolation("marketplace_assets")
    _enable_tenant_isolation("takedown_drafts")


def downgrade() -> None:
    op.drop_table("takedown_drafts")
    op.drop_table("marketplace_assets")
