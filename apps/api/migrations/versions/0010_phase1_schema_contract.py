"""Complete Phase 1 field contracts and tenant-bound referential integrity.

This additive revision also upgrades databases which have already adopted the
initial Phase 1 tables.  Evidence content is immutable; an investigation output
permits one attributable human disposition without rewriting generated content.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_phase1_schema_contract"
down_revision: str | None = "0009_phase1_rights_evidence_investigation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _unique(table: str, name: str, columns: list[str]) -> None:
    found = sa.inspect(op.get_bind()).get_unique_constraints(table)
    if any(item.get("name") == name for item in found):
        return
    with op.batch_alter_table(table) as batch:
        batch.create_unique_constraint(name, columns)


def _check(table: str, name: str, expression: str) -> None:
    found = sa.inspect(op.get_bind()).get_check_constraints(table)
    if any(item.get("name") == name for item in found):
        return
    with op.batch_alter_table(table) as batch:
        batch.create_check_constraint(name, expression)


def _foreign_key(
    table: str, name: str, columns: list[str], parent: str, targets: list[str]
) -> None:
    found = sa.inspect(op.get_bind()).get_foreign_keys(table)
    if any(item.get("name") == name for item in found):
        return
    with op.batch_alter_table(table) as batch:
        batch.create_foreign_key(name, parent, columns, targets)


def _backfill_immutable_rows(table: str, statement: str) -> None:
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        # A quick-start process may already have installed our SQL guards on an
        # older schema. Suspend only this maintenance table's update guard and
        # restore its exact definition; revision 0012 reconciles final columns.
        name = f"{table}_creatorproof_update_guard"
        guard = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
        ).scalar_one_or_none()
        if guard:
            op.execute(f'DROP TRIGGER "{name}"')
        op.execute(statement)
        if guard:
            connection.exec_driver_sql(guard)
        return
    if connection.dialect.name != "postgresql":
        op.execute(statement)
        return
    # FORCE RLS applies to table owners as well. Schema maintenance must see
    # every historical row, then restore the caller's transaction-local setting.
    previous_override = connection.execute(
        sa.text("SELECT current_setting('app.bypass_rls', true)")
    ).scalar_one()
    connection.execute(sa.text("SELECT set_config('app.bypass_rls', 'on', true)"))
    op.execute(f"ALTER TABLE {table} DISABLE TRIGGER {table}_append_only")
    op.execute(statement)
    op.execute(f"ALTER TABLE {table} ENABLE TRIGGER {table}_append_only")
    connection.execute(
        sa.text("SELECT set_config('app.bypass_rls', :previous, true)"),
        {"previous": previous_override or ""},
    )


_PARENT_IDENTITIES = (
    ("works", "uq_work_tenant_identity"),
    ("scans", "uq_scan_tenant_identity"),
    ("asset_versions", "uq_asset_version_tenant_identity"),
    ("provenance_records", "uq_provenance_tenant_identity"),
    ("investigation_runs", "uq_investigation_run_tenant_identity"),
    ("investigation_outputs", "uq_investigation_output_tenant_identity"),
    ("evidence_matrices", "uq_evidence_matrix_tenant_identity"),
)

_FOREIGN_KEYS = (
    ("rights_policy_versions", "fk_rights_policy_tenant_work", "work_id", "works"),
    ("provenance_records", "fk_provenance_tenant_work", "work_id", "works"),
    ("provenance_records", "fk_provenance_tenant_scan", "scan_id", "scans"),
    (
        "provenance_ingredients",
        "fk_provenance_ingredient_tenant_record",
        "record_id",
        "provenance_records",
    ),
    ("evidence_signals", "fk_evidence_signal_tenant_scan", "scan_id", "scans"),
    ("evidence_coverages", "fk_evidence_coverage_tenant_scan", "scan_id", "scans"),
    ("evidence_matrices", "fk_evidence_matrix_tenant_scan", "scan_id", "scans"),
    (
        "evidence_matrices",
        "fk_evidence_matrix_tenant_predecessor",
        "previous_matrix_id",
        "evidence_matrices",
    ),
    ("evidence_signals", "fk_evidence_signal_tenant_matrix", "matrix_id", "evidence_matrices"),
    ("evidence_coverages", "fk_evidence_coverage_tenant_matrix", "matrix_id", "evidence_matrices"),
    ("contribution_events", "fk_contribution_tenant_work", "work_id", "works"),
    (
        "contribution_events",
        "fk_contribution_tenant_output_asset",
        "output_asset_id",
        "asset_versions",
    ),
    ("investigation_runs", "fk_investigation_run_tenant_scan", "scan_id", "scans"),
    ("investigation_outputs", "fk_investigation_output_tenant_run", "run_id", "investigation_runs"),
    (
        "takedown_drafts",
        "fk_takedown_draft_tenant_investigation_output",
        "investigation_output_id",
        "investigation_outputs",
    ),
)


def _install_output_trigger() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        """
        CREATE OR REPLACE FUNCTION creatorproof_investigation_disposition_once()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'CreatorProof: investigation output cannot be deleted'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            IF (to_jsonb(NEW) - ARRAY['human_decision', 'human_decision_by', 'human_decision_at'])
               IS DISTINCT FROM
               (to_jsonb(OLD) - ARRAY['human_decision', 'human_decision_by', 'human_decision_at'])
               OR OLD.human_decision IS NOT NULL
               OR NEW.human_decision IS NULL
               OR NEW.human_decision NOT IN ('ACCEPTED', 'EDITED', 'REJECTED')
               OR NEW.human_decision_by IS NULL OR NEW.human_decision_by = ''
               OR NEW.human_decision_at IS NULL THEN
                RAISE EXCEPTION
                    'CreatorProof: generated investigation content is immutable; '
                    'only the first attributable human disposition is permitted'
                    USING ERRCODE = 'restrict_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS investigation_outputs_disposition_once ON investigation_outputs"
    )
    op.execute(
        """
        CREATE TRIGGER investigation_outputs_disposition_once
        BEFORE UPDATE OR DELETE ON investigation_outputs
        FOR EACH ROW EXECUTE FUNCTION creatorproof_investigation_disposition_once()
        """
    )


def upgrade() -> None:
    _add_column("works", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    indexes = {
        item.get("name") for item in sa.inspect(op.get_bind()).get_indexes("provenance_records")
    }
    if "ix_provenance_records_subject_id" not in indexes:
        op.create_index("ix_provenance_records_subject_id", "provenance_records", ["subject_id"])
    _add_column(
        "evidence_matrices", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    _add_column("evidence_matrices", sa.Column("previous_matrix_id", sa.String(64), nullable=True))
    matrix_constraints = {
        item.get("name")
        for item in sa.inspect(op.get_bind()).get_unique_constraints("evidence_matrices")
    }
    if "uq_evidence_matrix_scan" in matrix_constraints:
        with op.batch_alter_table("evidence_matrices") as batch:
            batch.drop_constraint("uq_evidence_matrix_scan", type_="unique")
    with op.batch_alter_table("evidence_matrices") as batch:
        batch.alter_column("version", existing_type=sa.Integer(), server_default=None)
    for table in ("evidence_signals", "evidence_coverages"):
        if "matrix_id" not in _columns(table):
            _add_column(table, sa.Column("matrix_id", sa.String(64), nullable=True))
            _backfill_immutable_rows(
                table,
                f"UPDATE {table} SET matrix_id = (SELECT id FROM evidence_matrices "
                f"WHERE evidence_matrices.tenant_id = {table}.tenant_id "
                f"AND evidence_matrices.scan_id = {table}.scan_id "
                "AND evidence_matrices.version = 1) WHERE matrix_id IS NULL",
            )
    for table, column in (
        ("evidence_matrices", "previous_matrix_id"),
        ("evidence_signals", "matrix_id"),
        ("evidence_coverages", "matrix_id"),
    ):
        name = f"ix_{table}_{column}"
        indexes = {item.get("name") for item in sa.inspect(op.get_bind()).get_indexes(table)}
        if name not in indexes:
            op.create_index(name, table, [column])
    for name, type_ in (
        ("confidence_level", sa.String(40)),
        ("coverage_status", sa.String(40)),
        ("model_or_rule_identifier", sa.String(160)),
        ("started_at", sa.DateTime(timezone=True)),
        ("completed_at", sa.DateTime(timezone=True)),
    ):
        _add_column("evidence_signals", sa.Column(name, type_, nullable=True))

    _add_column(
        "contribution_events",
        sa.Column("input_asset_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    for name, type_ in (
        ("output_asset_id", sa.String(64)),
        ("software_or_model", sa.String(240)),
        ("human_decision", sa.Text()),
        ("evidence_artifact_reference", sa.String(512)),
        ("c2pa_reference", sa.String(512)),
        ("created_by", sa.String(160)),
    ):
        _add_column("contribution_events", sa.Column(name, type_, nullable=True))
    if "timestamp" not in _columns("contribution_events"):
        _add_column(
            "contribution_events", sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True)
        )
        # This records the existing factual creation time rather than presenting
        # the schema upgrade time as a human contribution timestamp.
        _backfill_immutable_rows(
            "contribution_events",
            "UPDATE contribution_events SET timestamp = created_at WHERE timestamp IS NULL",
        )
    with op.batch_alter_table("contribution_events") as batch:
        batch.alter_column("input_asset_ids", existing_type=sa.JSON(), server_default=None)
        batch.alter_column("timestamp", existing_type=sa.DateTime(timezone=True), nullable=False)

    for table, name in _PARENT_IDENTITIES:
        _unique(table, name, ["tenant_id", "id"])
    _unique(
        "evidence_matrices", "uq_evidence_matrix_scan_version", ["tenant_id", "scan_id", "version"]
    )
    _unique(
        "contribution_events", "uq_contribution_work_sequence", ["tenant_id", "work_id", "sequence"]
    )
    for table, name, column, parent in _FOREIGN_KEYS:
        _foreign_key(table, name, ["tenant_id", column], parent, ["tenant_id", "id"])
    for table, name, expression in (
        ("rights_policy_versions", "ck_rights_policy_positive_version", "version >= 1"),
        (
            "rights_policy_versions",
            "ck_rights_policy_effective_interval",
            "effective_from IS NULL OR effective_until IS NULL OR effective_until > effective_from",
        ),
        (
            "evidence_signals",
            "ck_evidence_signal_confidence_range",
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
        ),
        (
            "evidence_signals",
            "ck_evidence_signal_time_order",
            "started_at IS NULL OR completed_at IS NULL OR completed_at >= started_at",
        ),
        (
            "evidence_coverages",
            "ck_evidence_coverage_percent_range",
            "coverage_percent IS NULL OR (coverage_percent >= 0 AND coverage_percent <= 100)",
        ),
        ("contribution_events", "ck_contribution_positive_sequence", "sequence >= 1"),
        ("evidence_matrices", "ck_evidence_matrix_positive_version", "version >= 1"),
        (
            "investigation_outputs",
            "ck_investigation_output_human_decision",
            "(human_decision IS NULL AND human_decision_by IS NULL AND human_decision_at IS NULL) "
            "OR (human_decision IN ('ACCEPTED', 'EDITED', 'REJECTED') "
            "AND human_decision_by IS NOT NULL AND human_decision_at IS NOT NULL)",
        ),
    ):
        _check(table, name, expression)
    _install_output_trigger()


def downgrade() -> None:
    # Removing the timestamp, tenancy FKs or contribution uniqueness would
    # discard/reduce the evidence contract. Restoration is a backup operation.
    raise RuntimeError(
        "Phase 1 evidence schema is forward-only; restore a verified backup to roll back"
    )
