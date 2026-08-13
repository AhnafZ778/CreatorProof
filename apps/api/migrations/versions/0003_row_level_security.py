"""PostgreSQL row-level security and append-only enforcement.

RLS turns tenant isolation from a convention into a database guarantee: a query
that forgets ``WHERE tenant_id = ...`` returns nothing rather than another
organization's catalog. Append-only tables additionally refuse UPDATE and DELETE
at the database level, so a bug or a direct psql session cannot quietly rewrite
signed evidence.

SQLite has neither feature, so this revision is a no-op there and the ORM-level
guards in ``app/models.py`` and ``app/api/deps.py`` remain the development
equivalent.

Revision ID: 0003_row_level_security
Revises: 0002_platform_entities
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_row_level_security"
down_revision: str | None = "0002_platform_entities"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Every tenant-owned table. `audit_events` is intentionally excluded: it carries a
# nullable tenant for pre-authentication failures and is read through an
# administrative path only.
_TENANT_TABLES = (
    "works",
    "scans",
    "principals",
    "api_credentials",
    "deletion_receipts",
    "catalogs",
    "catalog_versions",
    "asset_versions",
    "corpus_snapshots",
    "scan_input_bindings",
    "evidence_statements",
    "parties",
    "creator_profiles",
    "claims",
    "licenses",
    "rights_events",
    "policy_versions",
    "review_cases",
    "review_events",
    "webhook_endpoints",
    "webhook_deliveries",
    "usage_records",
)

# Append-only records. Status columns that must still change are handled by the
# explicit exception below rather than by relaxing the whole table.
_IMMUTABLE_TABLES = (
    "catalog_versions",
    "asset_versions",
    "model_bundles",
    "corpus_snapshots",
    "scan_input_bindings",
    "transparency_leaves",
    "transparency_checkpoints",
    "rights_events",
    "policy_versions",
    "review_events",
)


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())

    for table in _TENANT_TABLES:
        if table not in existing:
            continue
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(
            f"""
            CREATE POLICY {table}_tenant_isolation ON {table}
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

    op.execute(
        """
        CREATE OR REPLACE FUNCTION creatorproof_reject_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'CreatorProof: % is append-only; issue a new record instead', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in _IMMUTABLE_TABLES:
        if table not in existing:
            continue
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION creatorproof_reject_mutation()
            """
        )

    # A statement's bytes are immutable, but its current status must still move to
    # DISPUTED, SUPERSEDED or REVOKED. The trigger allows exactly that column to
    # change and blocks everything else.
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
    if "evidence_statements" in existing:
        op.execute(
            "DROP TRIGGER IF EXISTS evidence_statements_append_only ON evidence_statements"
        )
        op.execute(
            """
            CREATE TRIGGER evidence_statements_append_only
            BEFORE UPDATE OR DELETE ON evidence_statements
            FOR EACH ROW EXECUTE FUNCTION creatorproof_statement_status_only()
            """
        )


def downgrade() -> None:
    if not _is_postgres():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "evidence_statements" in existing:
        op.execute(
            "DROP TRIGGER IF EXISTS evidence_statements_append_only ON evidence_statements"
        )
    for table in _IMMUTABLE_TABLES:
        if table in existing:
            op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS creatorproof_statement_status_only()")
    op.execute("DROP FUNCTION IF EXISTS creatorproof_reject_mutation()")
    for table in _TENANT_TABLES:
        if table not in existing:
            continue
        op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
