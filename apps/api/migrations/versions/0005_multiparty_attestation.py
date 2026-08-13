"""Counterparty co-attestation and the mirrored network member registry.

Revision ID: 0005_multiparty_attestation
Revises: 0004_blockchain_integrity
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_multiparty_attestation"
down_revision: str | None = "0004_blockchain_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _create_index_if_missing(
    name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item.get("name") for item in inspector.get_indexes(table_name)}
    existing |= {item.get("name") for item in inspector.get_unique_constraints(table_name)}
    if name not in existing:
        op.create_index(name, table_name, columns, unique=unique)


def _enable_tenant_isolation(table_name: str) -> None:
    op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {table_name}_tenant_isolation ON {table_name}")
    op.execute(
        f"""
        CREATE POLICY {table_name}_tenant_isolation ON {table_name}
        USING (
            tenant_id = current_setting('app.tenant_id', true)
            OR current_setting('app.bypass_rls', true) = 'on'
        )
        WITH CHECK (
            tenant_id = current_setting('app.tenant_id', true)
            OR current_setting('app.bypass_rls', true) = 'on'
        )
        """
    )


def upgrade() -> None:
    if not _table_exists("network_members"):
        op.create_table(
            "network_members",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("address", sa.String(length=42), nullable=False),
            sa.Column("org_id", sa.String(length=120), nullable=False),
            sa.Column("display_name", sa.String(length=240), nullable=False),
            sa.Column("role", sa.String(length=40), nullable=False),
            sa.Column("status", sa.String(length=40), nullable=False),
            sa.Column("on_chain_org_id", sa.String(length=66), nullable=True),
            sa.Column("attributes", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint("length(address) = 42", name="ck_network_member_address_length"),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "address", name="uq_network_member_address"),
        )
    _create_index_if_missing("ix_network_member_status", "network_members", ["tenant_id", "status"])
    _create_index_if_missing("ix_network_members_tenant_id", "network_members", ["tenant_id"])
    _create_index_if_missing("ix_network_members_address", "network_members", ["address"])

    if not _table_exists("counterparty_attestations"):
        op.create_table(
            "counterparty_attestations",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("scan_id", sa.String(length=64), nullable=False),
            sa.Column("member_id", sa.String(length=64), nullable=True),
            sa.Column("signer_address", sa.String(length=42), nullable=False),
            sa.Column("party_role", sa.String(length=40), nullable=False),
            sa.Column("decision", sa.String(length=60), nullable=False),
            sa.Column("packet_hash_sha256", sa.String(length=64), nullable=False),
            sa.Column("platform_attestation_uid", sa.String(length=66), nullable=True),
            sa.Column("body", sa.JSON(), nullable=False),
            sa.Column("body_hash_sha256", sa.String(length=64), nullable=False),
            sa.Column("signature", sa.Text(), nullable=False),
            sa.Column("signature_alg", sa.String(length=40), nullable=False),
            sa.Column("membership_evidence", sa.JSON(), nullable=False),
            sa.Column("state", sa.String(length=40), nullable=False),
            sa.Column("anchor_job_id", sa.String(length=64), nullable=True),
            sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "length(body_hash_sha256) = 64",
                name="ck_counterparty_attestation_body_hash_length",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id", "body_hash_sha256", name="uq_counterparty_attestation_body"
            ),
        )
    for name, columns in (
        ("ix_counterparty_attestation_scan", ["tenant_id", "scan_id"]),
        ("ix_counterparty_attestation_signer", ["tenant_id", "signer_address"]),
        ("ix_counterparty_attestations_tenant_id", ["tenant_id"]),
        ("ix_counterparty_attestations_scan_id", ["scan_id"]),
        ("ix_counterparty_attestations_packet_hash_sha256", ["packet_hash_sha256"]),
        ("ix_counterparty_attestations_body_hash_sha256", ["body_hash_sha256"]),
        ("ix_counterparty_attestations_anchor_job_id", ["anchor_job_id"]),
    ):
        _create_index_if_missing(name, "counterparty_attestations", columns)

    if op.get_bind().dialect.name == "postgresql":
        _enable_tenant_isolation("network_members")
        _enable_tenant_isolation("counterparty_attestations")
        # A collected counterparty signature is evidence. Its body, hash and
        # signature are write-once; only anchoring progress and withdrawal move.
        op.execute(
            """
            CREATE OR REPLACE FUNCTION creatorproof_counterparty_signature_immutable()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION
                        'CreatorProof: counterparty attestations cannot be deleted'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.scan_id IS DISTINCT FROM OLD.scan_id
                   OR NEW.signer_address IS DISTINCT FROM OLD.signer_address
                   OR NEW.decision IS DISTINCT FROM OLD.decision
                   OR NEW.packet_hash_sha256 IS DISTINCT FROM OLD.packet_hash_sha256
                   OR NEW.body IS DISTINCT FROM OLD.body
                   OR NEW.body_hash_sha256 IS DISTINCT FROM OLD.body_hash_sha256
                   OR NEW.signature IS DISTINCT FROM OLD.signature
                   OR NEW.signature_alg IS DISTINCT FROM OLD.signature_alg
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION
                        'CreatorProof: a signed counterparty commitment is immutable; '
                        'withdraw it and collect a new signature'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER counterparty_attestations_signature_immutable
            BEFORE UPDATE OR DELETE ON counterparty_attestations
            FOR EACH ROW EXECUTE FUNCTION creatorproof_counterparty_signature_immutable()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS counterparty_attestations_signature_immutable "
            "ON counterparty_attestations"
        )
        op.execute("DROP FUNCTION IF EXISTS creatorproof_counterparty_signature_immutable()")
        op.execute(
            "DROP POLICY IF EXISTS counterparty_attestations_tenant_isolation "
            "ON counterparty_attestations"
        )
        op.execute("DROP POLICY IF EXISTS network_members_tenant_isolation ON network_members")
    op.drop_table("counterparty_attestations")
    op.drop_table("network_members")
