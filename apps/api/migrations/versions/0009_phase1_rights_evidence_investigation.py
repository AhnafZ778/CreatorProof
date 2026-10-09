"""Phase 1 rights passport, evidence matrix and investigation persistence.

All records that describe historical evidence are append-only.  Lifecycle rows
for an investigation and public token are intentionally mutable so workers can
report completion and operators can revoke access.  The migration is guarded so
it can upgrade both a legacy database and a database initialized with
``Base.metadata.create_all``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_phase1_rights_evidence_investigation"
down_revision: str | None = "0008_user_detection_notice_context"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _create_index_if_missing(
    name: str, table: str, columns: list[str], *, unique: bool = False
) -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {item.get("name") for item in inspector.get_indexes(table)}
    existing |= {item.get("name") for item in inspector.get_unique_constraints(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    inspector = sa.inspect(op.get_bind())
    names = {item["name"] for item in inspector.get_columns(table)}
    if column.name not in names:
        op.add_column(table, column)


def _enable_tenant_isolation(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql" or not _table_exists(table):
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


_IMMUTABLE_TABLES = (
    "rights_policy_versions",
    "provenance_records",
    "provenance_ingredients",
    "evidence_signals",
    "evidence_coverages",
    "evidence_matrices",
    "contribution_events",
)


def _install_immutable_triggers() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION creatorproof_phase1_reject_mutation()
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
        if not _table_exists(table):
            continue
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute(
            f"""
            CREATE TRIGGER {table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION creatorproof_phase1_reject_mutation()
            """
        )


def upgrade() -> None:
    if not _table_exists("rights_policy_versions"):
        op.create_table(
            "rights_policy_versions",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("work_id", sa.String(64), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("permissions", sa.JSON(), nullable=False),
            sa.Column("dimensions", sa.JSON(), nullable=False),
            sa.Column("creator_assertions", sa.JSON(), nullable=False),
            sa.Column("consent_metadata", sa.JSON(), nullable=False),
            sa.Column("revocation_metadata", sa.JSON(), nullable=False),
            sa.Column("corroboration", sa.JSON(), nullable=False),
            sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("superseded_by_id", sa.String(64), nullable=True),
            sa.Column("digest_sha256", sa.String(64), nullable=False),
            sa.Column("created_by_principal_id", sa.String(64), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "tenant_id", "work_id", "version", name="uq_rights_policy_work_version"
            ),
        )
    _create_index_if_missing(
        "ix_rights_policy_versions_tenant_id", "rights_policy_versions", ["tenant_id"]
    )
    _create_index_if_missing(
        "ix_rights_policy_work", "rights_policy_versions", ["tenant_id", "work_id", "created_at"]
    )
    _create_index_if_missing(
        "ix_rights_policy_versions_work_id", "rights_policy_versions", ["work_id"]
    )
    _create_index_if_missing(
        "ix_rights_policy_versions_digest_sha256", "rights_policy_versions", ["digest_sha256"]
    )

    if not _table_exists("provenance_records"):
        op.create_table(
            "provenance_records",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("subject_type", sa.String(40), nullable=False),
            sa.Column("subject_id", sa.String(64), nullable=False),
            sa.Column("scan_id", sa.String(64), nullable=True),
            sa.Column("work_id", sa.String(64), nullable=True),
            sa.Column("input_sha256", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(120), nullable=False),
            sa.Column("provider_version", sa.String(160), nullable=True),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("legacy_status", sa.String(40), nullable=True),
            sa.Column("reason_codes", sa.JSON(), nullable=False),
            sa.Column("manifest_summary", sa.JSON(), nullable=False),
            sa.Column("trust_details", sa.JSON(), nullable=False),
            sa.Column("metadata_summary", sa.JSON(), nullable=False),
            sa.Column("artifact_refs", sa.JSON(), nullable=False),
            sa.Column("error_code", sa.String(160), nullable=True),
            sa.Column("fallback_used", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    for name, cols in (
        ("ix_provenance_records_tenant_id", ["tenant_id"]),
        ("ix_provenance_subject", ["tenant_id", "subject_type", "subject_id"]),
        ("ix_provenance_scan", ["tenant_id", "scan_id"]),
        ("ix_provenance_records_scan_id", ["scan_id"]),
        ("ix_provenance_records_work_id", ["work_id"]),
        ("ix_provenance_records_input_sha256", ["input_sha256"]),
    ):
        _create_index_if_missing(name, "provenance_records", cols)

    if not _table_exists("provenance_ingredients"):
        op.create_table(
            "provenance_ingredients",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("record_id", sa.String(64), nullable=False),
            sa.Column("ingredient_id", sa.String(240), nullable=False),
            sa.Column("relationship", sa.String(120), nullable=False),
            sa.Column("source_reference", sa.String(512), nullable=True),
            sa.Column("input_sha256", sa.String(64), nullable=True),
            sa.Column("trust_status", sa.String(40), nullable=True),
            sa.Column("metadata_summary", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing(
        "ix_provenance_ingredients_tenant_id", "provenance_ingredients", ["tenant_id"]
    )
    _create_index_if_missing(
        "ix_provenance_ingredient_record", "provenance_ingredients", ["tenant_id", "record_id"]
    )
    _create_index_if_missing(
        "ix_provenance_ingredients_record_id", "provenance_ingredients", ["record_id"]
    )

    if not _table_exists("evidence_signals"):
        op.create_table(
            "evidence_signals",
            sa.Column("signal_id", sa.String(96), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("scan_id", sa.String(64), nullable=False),
            sa.Column("lane", sa.String(40), nullable=False),
            sa.Column("provider", sa.String(120), nullable=False),
            sa.Column("provider_version", sa.String(160), nullable=True),
            sa.Column("signal_type", sa.String(80), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("score_semantics", sa.String(160), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("evidence_quality", sa.String(40), nullable=True),
            sa.Column("coverage", sa.JSON(), nullable=False),
            sa.Column("reason_codes", sa.JSON(), nullable=False),
            sa.Column("artifact_refs", sa.JSON(), nullable=False),
            sa.Column("input_sha256", sa.String(64), nullable=True),
            sa.Column("error_code", sa.String(160), nullable=True),
            sa.Column("fallback_used", sa.Boolean(), nullable=False),
            sa.Column("model_version", sa.String(160), nullable=True),
            sa.Column("rule_version", sa.String(160), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("signal_id"),
            sa.UniqueConstraint("tenant_id", "signal_id", name="uq_evidence_signal_id"),
        )
    _create_index_if_missing("ix_evidence_signals_tenant_id", "evidence_signals", ["tenant_id"])
    _create_index_if_missing(
        "ix_evidence_signal_scan", "evidence_signals", ["tenant_id", "scan_id", "lane"]
    )
    _create_index_if_missing("ix_evidence_signals_scan_id", "evidence_signals", ["scan_id"])
    _create_index_if_missing("ix_evidence_signals_lane", "evidence_signals", ["lane"])

    if not _table_exists("evidence_coverages"):
        op.create_table(
            "evidence_coverages",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("scan_id", sa.String(64), nullable=False),
            sa.Column("lane", sa.String(40), nullable=False),
            sa.Column("provider", sa.String(120), nullable=False),
            sa.Column("requested_scope", sa.JSON(), nullable=False),
            sa.Column("completed_scope", sa.JSON(), nullable=False),
            sa.Column("unavailable_scope", sa.JSON(), nullable=False),
            sa.Column("coverage_percent", sa.Float(), nullable=True),
            sa.Column("reason_codes", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_evidence_coverages_tenant_id", "evidence_coverages", ["tenant_id"])
    _create_index_if_missing(
        "ix_evidence_coverage_scan", "evidence_coverages", ["tenant_id", "scan_id", "lane"]
    )
    _create_index_if_missing("ix_evidence_coverages_scan_id", "evidence_coverages", ["scan_id"])

    if not _table_exists("evidence_matrices"):
        op.create_table(
            "evidence_matrices",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("scan_id", sa.String(64), nullable=False),
            sa.Column("matrix_version", sa.String(80), nullable=False),
            sa.Column("final_status", sa.String(80), nullable=False),
            sa.Column("abstention", sa.Boolean(), nullable=False),
            sa.Column("abstention_code", sa.String(120), nullable=True),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("recommended_action", sa.String(80), nullable=True),
            sa.Column("policy_decision_id", sa.String(64), nullable=True),
            sa.Column("packet_hash_sha256", sa.String(64), nullable=True),
            sa.Column("coverage_summary", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "scan_id", name="uq_evidence_matrix_scan"),
        )
    _create_index_if_missing("ix_evidence_matrices_tenant_id", "evidence_matrices", ["tenant_id"])
    _create_index_if_missing("ix_evidence_matrices_scan_id", "evidence_matrices", ["scan_id"])
    _create_index_if_missing(
        "ix_evidence_matrices_packet_hash_sha256", "evidence_matrices", ["packet_hash_sha256"]
    )

    if not _table_exists("contribution_events"):
        op.create_table(
            "contribution_events",
            sa.Column("event_id", sa.String(96), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("work_id", sa.String(64), nullable=False),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("actor_type", sa.String(40), nullable=False),
            sa.Column("actor_id", sa.String(160), nullable=True),
            sa.Column("event_type", sa.String(80), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("classification", sa.String(80), nullable=False),
            sa.Column("provider", sa.String(120), nullable=True),
            sa.Column("model", sa.String(160), nullable=True),
            sa.Column("input_hash", sa.String(64), nullable=True),
            sa.Column("output_hash", sa.String(64), nullable=True),
            sa.Column("prompt_reference", sa.String(256), nullable=True),
            sa.Column("previous_event_hash", sa.String(64), nullable=True),
            sa.Column("event_hash", sa.String(64), nullable=False),
            sa.Column("source_reference", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("event_id"),
            sa.UniqueConstraint("tenant_id", "event_id", name="uq_contribution_event_id"),
        )
    _create_index_if_missing(
        "ix_contribution_events_tenant_id", "contribution_events", ["tenant_id"]
    )
    _create_index_if_missing(
        "ix_contribution_work_sequence", "contribution_events", ["tenant_id", "work_id", "sequence"]
    )
    _create_index_if_missing("ix_contribution_events_work_id", "contribution_events", ["work_id"])
    _create_index_if_missing(
        "ix_contribution_events_event_hash", "contribution_events", ["event_hash"]
    )

    if not _table_exists("investigation_runs"):
        op.create_table(
            "investigation_runs",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("scan_id", sa.String(64), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("requested_by", sa.String(160), nullable=True),
            sa.Column("provider", sa.String(120), nullable=False),
            sa.Column("model", sa.String(160), nullable=True),
            sa.Column("prompt_template_version", sa.String(80), nullable=False),
            sa.Column("evidence_packet_hash", sa.String(64), nullable=True),
            sa.Column("input_hash", sa.String(64), nullable=True),
            sa.Column("error_code", sa.String(160), nullable=True),
            sa.Column("retry_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_investigation_runs_tenant_id", "investigation_runs", ["tenant_id"])
    _create_index_if_missing(
        "ix_investigation_run_scan", "investigation_runs", ["tenant_id", "scan_id", "created_at"]
    )
    _create_index_if_missing("ix_investigation_runs_scan_id", "investigation_runs", ["scan_id"])

    if not _table_exists("investigation_outputs"):
        op.create_table(
            "investigation_outputs",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("run_id", sa.String(64), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("evidence_references", sa.JSON(), nullable=False),
            sa.Column("missing_facts", sa.JSON(), nullable=False),
            sa.Column("next_steps", sa.JSON(), nullable=False),
            sa.Column("duplicate_groups", sa.JSON(), nullable=False),
            sa.Column("factual_notice_draft", sa.JSON(), nullable=True),
            sa.Column("unsupported_claims", sa.JSON(), nullable=False),
            sa.Column("output_hash", sa.String(64), nullable=False),
            sa.Column("provider", sa.String(120), nullable=False),
            sa.Column("model", sa.String(160), nullable=True),
            sa.Column("human_decision", sa.String(32), nullable=True),
            sa.Column("human_decision_by", sa.String(160), nullable=True),
            sa.Column("human_decision_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("tenant_id", "run_id", name="uq_investigation_output_run"),
        )
    _create_index_if_missing(
        "ix_investigation_outputs_tenant_id", "investigation_outputs", ["tenant_id"]
    )
    _create_index_if_missing("ix_investigation_outputs_run_id", "investigation_outputs", ["run_id"])
    _create_index_if_missing(
        "ix_investigation_outputs_output_hash", "investigation_outputs", ["output_hash"]
    )

    if not _table_exists("public_verification_tokens"):
        op.create_table(
            "public_verification_tokens",
            sa.Column("id", sa.String(64), nullable=False),
            sa.Column("tenant_id", sa.String(64), sa.ForeignKey("tenants.id"), nullable=False),
            sa.Column("resource_type", sa.String(40), nullable=False),
            sa.Column("resource_id", sa.String(64), nullable=False),
            sa.Column("token_hash", sa.String(128), nullable=False),
            sa.Column("scopes", sa.JSON(), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_by", sa.String(160), nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token_hash", name="uq_public_verification_token_hash"),
        )
    _create_index_if_missing(
        "ix_public_verification_tokens_tenant_id", "public_verification_tokens", ["tenant_id"]
    )
    _create_index_if_missing(
        "ix_public_verification_token_lookup", "public_verification_tokens", ["token_hash"]
    )
    _create_index_if_missing(
        "ix_public_verification_resource",
        "public_verification_tokens",
        ["tenant_id", "resource_type", "resource_id"],
    )
    _create_index_if_missing(
        "ix_public_verification_tokens_resource_id", "public_verification_tokens", ["resource_id"]
    )

    if _table_exists("takedown_drafts"):
        _add_column_if_missing(
            "takedown_drafts", sa.Column("investigation_output_id", sa.String(64), nullable=True)
        )
        _create_index_if_missing(
            "ix_takedown_drafts_investigation_output_id",
            "takedown_drafts",
            ["investigation_output_id"],
        )

    for table in (
        "rights_policy_versions",
        "provenance_records",
        "provenance_ingredients",
        "evidence_signals",
        "evidence_coverages",
        "evidence_matrices",
        "contribution_events",
        "investigation_runs",
        "investigation_outputs",
        "public_verification_tokens",
    ):
        _enable_tenant_isolation(table)
    _install_immutable_triggers()


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in _IMMUTABLE_TABLES:
            if _table_exists(table):
                op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute("DROP FUNCTION IF EXISTS creatorproof_phase1_reject_mutation()")
        for table in (
            "rights_policy_versions",
            "provenance_records",
            "provenance_ingredients",
            "evidence_signals",
            "evidence_coverages",
            "evidence_matrices",
            "contribution_events",
            "investigation_runs",
            "investigation_outputs",
            "public_verification_tokens",
        ):
            if _table_exists(table):
                op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
                op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    if _table_exists("takedown_drafts"):
        inspector = sa.inspect(op.get_bind())
        indexes = {item.get("name") for item in inspector.get_indexes("takedown_drafts")}
        if "ix_takedown_drafts_investigation_output_id" in indexes:
            op.drop_index(
                "ix_takedown_drafts_investigation_output_id", table_name="takedown_drafts"
            )
        columns = {item["name"] for item in inspector.get_columns("takedown_drafts")}
        if "investigation_output_id" in columns:
            op.drop_column("takedown_drafts", "investigation_output_id")

    for table in (
        "public_verification_tokens",
        "investigation_outputs",
        "investigation_runs",
        "contribution_events",
        "evidence_matrices",
        "evidence_coverages",
        "evidence_signals",
        "provenance_ingredients",
        "provenance_records",
        "rights_policy_versions",
    ):
        if _table_exists(table):
            op.drop_table(table)
