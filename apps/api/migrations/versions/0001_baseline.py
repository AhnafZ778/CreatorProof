"""Baseline schema matching the pre-migration v0.9.1/v0.9.2 database.

Every step is guarded by an inspector check so this revision is safe to run both
on an empty database and on an existing prototype database that was created with
``Base.metadata.create_all``. That removes the manual ``alembic stamp`` step that
otherwise makes an upgrade of a live database error-prone.

Revision ID: 0001_baseline
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    existing = _tables()

    if "tenants" not in existing:
        op.create_table(
            "tenants",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("slug", sa.String(80), nullable=False, unique=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    if "works" not in existing:
        op.create_table(
            "works",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("catalog_id", sa.String(120), nullable=False),
            sa.Column("title", sa.String(240), nullable=False),
            sa.Column("sha256", sa.String(64), nullable=False),
            sa.Column("phash", sa.String(32), nullable=False),
            sa.Column("storage_key", sa.String(512), nullable=False),
            sa.Column("rights_path", sa.String(40), nullable=False),
            sa.Column("allowed_uses", sa.JSON(), nullable=False),
            sa.Column("claimant", sa.String(240), nullable=True),
            sa.Column("claim_state", sa.String(40), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_works_tenant_id", "works", ["tenant_id"])
        op.create_index("ix_works_catalog_id", "works", ["catalog_id"])
        op.create_index("ix_work_scope", "works", ["tenant_id", "catalog_id"])
        op.create_index("ix_work_sha", "works", ["tenant_id", "sha256"])

    if "scans" not in existing:
        op.create_table(
            "scans",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("idempotency_key", sa.String(160), nullable=False),
            sa.Column("catalog_id", sa.String(120), nullable=False),
            sa.Column("intended_use", sa.String(160), nullable=False),
            sa.Column("candidate_sha256", sa.String(64), nullable=False),
            sa.Column("candidate_phash", sa.String(32), nullable=False),
            sa.Column("candidate_storage_key", sa.String(512), nullable=True),
            sa.Column("state", sa.String(40), nullable=False),
            sa.Column("match_status", sa.String(64), nullable=True),
            sa.Column("policy_action", sa.String(40), nullable=True),
            sa.Column("rights_path", sa.String(40), nullable=True),
            sa.Column("anchor_status", sa.String(40), nullable=False),
            sa.Column("reason_codes", sa.JSON(), nullable=False),
            sa.Column("top_match_work_id", sa.String(64), nullable=True),
            sa.Column("evidence_packet", sa.JSON(), nullable=True),
            sa.Column("error_code", sa.String(100), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_scan_idempotency"),
        )
        op.create_index("ix_scans_tenant_id", "scans", ["tenant_id"])
        op.create_index("ix_scans_catalog_id", "scans", ["catalog_id"])
        op.create_index("ix_scan_tenant_created", "scans", ["tenant_id", "created_at"])


def downgrade() -> None:
    # The baseline is the oldest supported shape. Dropping it would destroy the
    # customer catalog, so the rollback path is a restore from backup instead.
    raise RuntimeError(
        "Refusing to drop the baseline schema. Restore from a verified backup instead."
    )
