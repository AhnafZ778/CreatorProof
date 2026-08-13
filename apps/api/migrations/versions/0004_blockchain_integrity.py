"""Durable signed domain events and recoverable blockchain anchor jobs.

Revision ID: 0004_blockchain_integrity
Revises: 0003_row_level_security
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_blockchain_integrity"
down_revision: str | None = "0003_row_level_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _named_index_or_constraint_exists(table_name: str, name: str) -> bool:
    """Recognize both create-all and Alembic representations of uniqueness.

    SQLite reports a named ``UniqueConstraint`` and a named unique ``Index``
    through different inspector collections. Older quick-start databases used
    the former for transparency replay protection, while this revision uses the
    latter so PostgreSQL and SQLite expose the same schema to Alembic.
    """
    inspector = sa.inspect(op.get_bind())
    indexes = {item.get("name") for item in inspector.get_indexes(table_name)}
    constraints = {
        item.get("name") for item in inspector.get_unique_constraints(table_name)
    }
    return name in indexes or name in constraints


def _index_exists(table_name: str, name: str) -> bool:
    return name in {
        item.get("name") for item in sa.inspect(op.get_bind()).get_indexes(table_name)
    }


def _unique_constraint_exists(table_name: str, name: str) -> bool:
    return name in {
        item.get("name")
        for item in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    }


def _create_index_if_missing(
    name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not _named_index_or_constraint_exists(table_name, name):
        op.create_index(name, table_name, columns, unique=unique)


def _normalize_unique_index(name: str, table_name: str, columns: list[str]) -> None:
    """Normalize an earlier create-all UniqueConstraint to the canonical index.

    A short-lived pre-migration model represented this invariant as a table
    constraint. Supporting that shape prevents a local SQLite database created
    during development from becoming stranded. Batch mode is required for SQLite
    because it cannot drop a table constraint in place.
    """
    if _unique_constraint_exists(table_name, name):
        if op.get_bind().dialect.name == "sqlite":
            with op.batch_alter_table(table_name) as batch_op:
                batch_op.drop_constraint(name, type_="unique")
        else:
            op.drop_constraint(name, table_name, type_="unique")
    if not _index_exists(table_name, name):
        op.create_index(name, table_name, columns, unique=True)


def upgrade() -> None:
    # A committed statement/event may be replayed after a process crash. Bind its
    # identifier to exactly one log leaf so recovery is idempotent across workers.
    duplicate_leaf = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT log_id, statement_id, COUNT(*) AS leaf_count "
                "FROM transparency_leaves WHERE statement_id IS NOT NULL "
                "GROUP BY log_id, statement_id HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate_leaf is not None:
        raise RuntimeError(
            "Cannot enforce transparency replay idempotency: "
            f"statement {duplicate_leaf[1]} in log {duplicate_leaf[0]} already has "
            f"{duplicate_leaf[2]} leaves; audit and remove the duplicate before migrating"
        )
    _normalize_unique_index(
        "uq_transparency_leaf_statement",
        "transparency_leaves",
        ["log_id", "statement_id"],
    )
    fork = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT previous_statement_id, COUNT(*) AS successor_count "
                "FROM evidence_statements WHERE previous_statement_id IS NOT NULL "
                "GROUP BY previous_statement_id HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if fork is not None:
        raise RuntimeError(
            "Cannot enforce linear evidence-statement lineage: "
            f"{fork[0]} already has {fork[1]} successors"
        )
    # NULL roots remain unlimited, while each non-NULL predecessor can have only
    # one correction/dispute/revocation successor.
    _create_index_if_missing(
        "uq_evidence_statement_successor",
        "evidence_statements",
        ["previous_statement_id"],
        unique=True,
    )

    if not _table_exists("integrity_events"):
        op.create_table(
            "integrity_events",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=False),
            sa.Column("event_type", sa.String(length=80), nullable=False),
            sa.Column("subject_type", sa.String(length=40), nullable=False),
            sa.Column("subject_id", sa.String(length=64), nullable=False),
            sa.Column("schema_version", sa.String(length=80), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("payload_digest_sha256", sa.String(length=64), nullable=False),
            sa.Column("signature_kid", sa.String(length=80), nullable=True),
            sa.Column("signature_alg", sa.String(length=40), nullable=True),
            sa.Column("signature_b64", sa.Text(), nullable=True),
            sa.Column("cose_sign1_b64", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "ix_integrity_event_subject",
        "integrity_events",
        ["tenant_id", "subject_type", "subject_id"],
    )
    _create_index_if_missing(
        "ix_integrity_event_digest", "integrity_events", ["payload_digest_sha256"]
    )
    _create_index_if_missing("ix_integrity_events_tenant_id", "integrity_events", ["tenant_id"])
    _create_index_if_missing("ix_integrity_events_event_type", "integrity_events", ["event_type"])

    if not _table_exists("blockchain_anchor_jobs"):
        op.create_table(
            "blockchain_anchor_jobs",
            sa.Column("id", sa.String(length=64), nullable=False),
            sa.Column("tenant_id", sa.String(length=64), nullable=True),
            sa.Column("deployment_id", sa.String(length=128), nullable=False),
            sa.Column("commitment_type", sa.String(length=60), nullable=False),
            sa.Column("commitment_hash_sha256", sa.String(length=64), nullable=False),
            sa.Column("subject_type", sa.String(length=40), nullable=False),
            sa.Column("subject_id", sa.String(length=80), nullable=False),
            sa.Column("context", sa.JSON(), nullable=False),
            sa.Column("state", sa.String(length=40), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False),
            sa.Column("max_attempts", sa.Integer(), nullable=False),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("lease_owner", sa.String(length=160), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("transaction_hash", sa.String(length=80), nullable=True),
            sa.Column("signed_transaction_hex", sa.Text(), nullable=True),
            sa.Column("transaction_nonce", sa.Integer(), nullable=True),
            sa.Column("chain_id", sa.Integer(), nullable=True),
            sa.Column("receipt", sa.JSON(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "length(commitment_hash_sha256) = 64",
                name="ck_blockchain_anchor_commitment_hash_length",
            ),
            sa.CheckConstraint(
                "attempts >= 0 AND max_attempts >= 1",
                name="ck_blockchain_anchor_attempts",
            ),
            sa.CheckConstraint(
                "transaction_hash IS NULL OR length(transaction_hash) = 66",
                name="ck_blockchain_anchor_transaction_hash_length",
            ),
            sa.CheckConstraint(
                "signed_transaction_hex IS NULL OR transaction_hash IS NOT NULL",
                name="ck_blockchain_anchor_signed_transaction_identity",
            ),
            sa.CheckConstraint(
                "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
                "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
                name="ck_blockchain_anchor_lease_pair",
            ),
            sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "deployment_id",
                "commitment_type",
                "commitment_hash_sha256",
                name="uq_blockchain_anchor_commitment",
            ),
        )
    _create_index_if_missing(
        "ix_blockchain_anchor_dispatch", "blockchain_anchor_jobs", ["state", "available_at"]
    )
    _create_index_if_missing(
        "ix_blockchain_anchor_subject", "blockchain_anchor_jobs", ["subject_type", "subject_id"]
    )
    _create_index_if_missing(
        "ix_blockchain_anchor_jobs_tenant_id", "blockchain_anchor_jobs", ["tenant_id"]
    )
    _create_index_if_missing(
        "ix_blockchain_anchor_jobs_commitment_hash_sha256",
        "blockchain_anchor_jobs",
        ["commitment_hash_sha256"],
    )
    _create_index_if_missing(
        "ix_blockchain_anchor_jobs_transaction_hash",
        "blockchain_anchor_jobs",
        ["transaction_hash"],
    )

    if not _table_exists("blockchain_signer_leases"):
        op.create_table(
            "blockchain_signer_leases",
            sa.Column("deployment_id", sa.String(length=128), nullable=False),
            sa.Column("lease_owner", sa.String(length=160), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "(lease_owner IS NULL AND lease_expires_at IS NULL) OR "
                "(lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
                name="ck_blockchain_signer_lease_pair",
            ),
            sa.PrimaryKeyConstraint("deployment_id"),
        )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE integrity_events ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE integrity_events FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY integrity_events_tenant_isolation ON integrity_events
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
        op.execute("ALTER TABLE blockchain_anchor_jobs ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE blockchain_anchor_jobs FORCE ROW LEVEL SECURITY")
        op.execute(
            "DROP POLICY IF EXISTS blockchain_anchor_jobs_tenant_isolation "
            "ON blockchain_anchor_jobs"
        )
        op.execute(
            """
            CREATE POLICY blockchain_anchor_jobs_tenant_isolation ON blockchain_anchor_jobs
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
        # A checkpoint's signed tree head stays append-only. Its public-chain
        # receipt is deliberately a one-time completion field so portable proof
        # packages do not depend on the mutable transaction queue forever.
        op.execute(
            "DROP TRIGGER IF EXISTS transparency_checkpoints_append_only "
            "ON transparency_checkpoints"
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION creatorproof_checkpoint_commitment_once()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'CreatorProof: transparency checkpoints cannot be deleted'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.log_id IS DISTINCT FROM OLD.log_id
                   OR NEW.tree_size IS DISTINCT FROM OLD.tree_size
                   OR NEW.root_sha256 IS DISTINCT FROM OLD.root_sha256
                   OR NEW.signature_kid IS DISTINCT FROM OLD.signature_kid
                   OR NEW.signature_b64 IS DISTINCT FROM OLD.signature_b64
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at
                   OR OLD.external_commitment IS NOT NULL
                   OR NEW.external_commitment IS NULL THEN
                    RAISE EXCEPTION
                        'CreatorProof: checkpoint content is immutable; '
                        'external commitment is write-once'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER transparency_checkpoints_external_commitment_once
            BEFORE UPDATE OR DELETE ON transparency_checkpoints
            FOR EACH ROW EXECUTE FUNCTION creatorproof_checkpoint_commitment_once()
            """
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION creatorproof_protect_blockchain_tx_identity()
            RETURNS trigger AS $$
            BEGIN
                IF OLD.transaction_hash IS NOT NULL AND
                   NEW.transaction_hash IS DISTINCT FROM OLD.transaction_hash THEN
                    RAISE EXCEPTION 'CreatorProof: prepared transaction hash is immutable'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF OLD.signed_transaction_hex IS NOT NULL AND
                   NEW.signed_transaction_hex IS DISTINCT FROM OLD.signed_transaction_hex THEN
                    RAISE EXCEPTION 'CreatorProof: signed transaction bytes are immutable'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF OLD.transaction_nonce IS NOT NULL AND
                   NEW.transaction_nonce IS DISTINCT FROM OLD.transaction_nonce THEN
                    RAISE EXCEPTION 'CreatorProof: prepared transaction nonce is immutable'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF OLD.chain_id IS NOT NULL AND NEW.chain_id IS DISTINCT FROM OLD.chain_id THEN
                    RAISE EXCEPTION 'CreatorProof: prepared transaction chain id is immutable'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER blockchain_anchor_jobs_tx_identity_immutable
            BEFORE UPDATE ON blockchain_anchor_jobs
            FOR EACH ROW EXECUTE FUNCTION creatorproof_protect_blockchain_tx_identity()
            """
        )
        op.execute(
            """
            CREATE OR REPLACE FUNCTION creatorproof_statement_status_only()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'CreatorProof: evidence statements cannot be deleted'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
                   OR NEW.scan_id IS DISTINCT FROM OLD.scan_id
                   OR NEW.statement_type IS DISTINCT FROM OLD.statement_type
                   OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
                   OR NEW.payload IS DISTINCT FROM OLD.payload
                   OR NEW.payload_digest_sha256 IS DISTINCT FROM OLD.payload_digest_sha256
                   OR NEW.signature_kid IS DISTINCT FROM OLD.signature_kid
                   OR NEW.signature_alg IS DISTINCT FROM OLD.signature_alg
                   OR NEW.signature_b64 IS DISTINCT FROM OLD.signature_b64
                   OR NEW.cose_sign1_b64 IS DISTINCT FROM OLD.cose_sign1_b64
                   OR NEW.previous_statement_id IS DISTINCT FROM OLD.previous_statement_id
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION
                        'CreatorProof: signed statement content is immutable; append a correction'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER integrity_events_append_only
            BEFORE UPDATE OR DELETE ON integrity_events
            FOR EACH ROW EXECUTE FUNCTION creatorproof_reject_mutation()
            """
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        # Restore the exact looser function installed by revision 0003. Its
        # existing evidence_statements trigger remains attached throughout.
        op.execute(
            """
            CREATE OR REPLACE FUNCTION creatorproof_statement_status_only()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'CreatorProof: evidence statements cannot be deleted'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                IF NEW.payload IS DISTINCT FROM OLD.payload
                   OR NEW.payload_digest_sha256 IS DISTINCT FROM OLD.payload_digest_sha256
                   OR NEW.signature_b64 IS DISTINCT FROM OLD.signature_b64
                   OR NEW.cose_sign1_b64 IS DISTINCT FROM OLD.cose_sign1_b64
                   OR NEW.signature_kid IS DISTINCT FROM OLD.signature_kid THEN
                    RAISE EXCEPTION
                        'CreatorProof: signed statement content is immutable; append a correction'
                        USING ERRCODE = 'restrict_violation';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            "DROP TRIGGER IF EXISTS transparency_checkpoints_external_commitment_once "
            "ON transparency_checkpoints"
        )
        op.execute("DROP FUNCTION IF EXISTS creatorproof_checkpoint_commitment_once()")
        op.execute(
            """
            CREATE TRIGGER transparency_checkpoints_append_only
            BEFORE UPDATE OR DELETE ON transparency_checkpoints
            FOR EACH ROW EXECUTE FUNCTION creatorproof_reject_mutation()
            """
        )
        op.execute(
            "DROP TRIGGER IF EXISTS blockchain_anchor_jobs_tx_identity_immutable "
            "ON blockchain_anchor_jobs"
        )
        op.execute("DROP FUNCTION IF EXISTS creatorproof_protect_blockchain_tx_identity()")
        op.execute("DROP TRIGGER IF EXISTS integrity_events_append_only ON integrity_events")
        op.execute(
            "DROP POLICY IF EXISTS blockchain_anchor_jobs_tenant_isolation "
            "ON blockchain_anchor_jobs"
        )
        op.execute("DROP POLICY IF EXISTS integrity_events_tenant_isolation ON integrity_events")
    op.drop_table("blockchain_signer_leases")
    op.drop_table("blockchain_anchor_jobs")
    op.drop_table("integrity_events")
    op.drop_index("uq_evidence_statement_successor", table_name="evidence_statements")
    op.drop_index("uq_transparency_leaf_statement", table_name="transparency_leaves")
