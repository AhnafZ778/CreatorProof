"""SQLite database guards for the same append-only records as the ORM.

SQLite has no separate runtime database role. These guards prevent Core SQL,
bulk writes and accidental replacement from bypassing application immutability;
the owner of the database file can still alter its schema, as with any SQLite
database. Portable signatures and hashes detect such compromised storage.
"""

from __future__ import annotations

from sqlalchemy import Connection, inspect

# Keep this contract explicit so migrations can install guards without importing
# live ORM models. Tests compare it against the declared immutable model tables.
SQLITE_IMMUTABLE_TABLES = frozenset(
    {
        "asset_versions",
        "catalog_versions",
        "contribution_events",
        "corpus_snapshots",
        "evidence_coverages",
        "evidence_matrices",
        "evidence_signals",
        "evidence_statements",
        "integrity_events",
        "investigation_outputs",
        "model_bundles",
        "policy_versions",
        "provenance_ingredients",
        "provenance_records",
        "review_events",
        "rights_events",
        "rights_policy_versions",
        "scan_input_bindings",
        "transparency_checkpoints",
        "transparency_leaves",
    }
)


def _unchanged_columns(columns: list[str], allowed: set[str]) -> str:
    return " OR ".join(
        f'NEW."{column}" IS NOT OLD."{column}"' for column in columns if column not in allowed
    )


def install_sqlite_integrity_guards(connection: Connection) -> None:
    """Install/reconcile triggers after migrations or SQLite create_all.

    This deliberately uses inspected columns, including any extra deployed
    columns, so future content fields are protected without a permissive gap.
    PostgreSQL guards remain migration-managed and are unaffected.
    """
    if connection.dialect.name != "sqlite":
        return
    inspector = inspect(connection)
    existing = set(inspector.get_table_names())
    for table in sorted(SQLITE_IMMUTABLE_TABLES & existing):
        columns = [item["name"] for item in inspector.get_columns(table)]
        condition = "1"
        if table == "investigation_outputs":
            condition = (
                _unchanged_columns(
                    columns, {"human_decision", "human_decision_by", "human_decision_at"}
                )
                + " OR OLD.human_decision IS NOT NULL OR NEW.human_decision IS NULL"
                + " OR NEW.human_decision NOT IN ('ACCEPTED', 'EDITED', 'REJECTED')"
                + " OR NEW.human_decision_by IS NULL OR trim(NEW.human_decision_by) = ''"
                + " OR NEW.human_decision_at IS NULL"
            )
        elif table == "transparency_checkpoints":
            condition = (
                _unchanged_columns(columns, {"external_commitment"})
                + " OR OLD.external_commitment IS NOT NULL OR NEW.external_commitment IS NULL"
            )
        elif table == "evidence_statements":
            # Compatibility: supersession/dispute/revocation appends a signed
            # successor and changes only this current-status projection.
            condition = _unchanged_columns(columns, {"status"})
        for operation, condition_ in (("UPDATE", condition), ("DELETE", "1")):
            name = f"{table}_creatorproof_{operation.lower()}_guard"
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{name}"')
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{name}" BEFORE {operation} ON "{table}" '
                f"FOR EACH ROW WHEN {condition_} BEGIN "
                f"SELECT RAISE(ABORT, 'CreatorProof: {table} is append-only; "
                "content is immutable'); END"
            )

        # SQLite's REPLACE implicitly deletes conflicting rows and may omit
        # delete triggers when recursive_triggers is disabled. Reject an insert
        # matching an existing primary/unique identity before conflict handling.
        identities = [inspector.get_pk_constraint(table).get("constrained_columns", [])]
        identities.extend(item["column_names"] for item in inspector.get_unique_constraints(table))
        identities.extend(
            item["column_names"] for item in inspector.get_indexes(table) if item.get("unique")
        )
        predicates = {
            " AND ".join(f'"{column}" = NEW."{column}"' for column in identity)
            for identity in identities
            if identity and all(column in columns for column in identity)
        }
        insert_name = f"{table}_creatorproof_insert_guard"
        connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS "{insert_name}"')
        if predicates:
            matches = " OR ".join(f"({value})" for value in sorted(predicates))
            connection.exec_driver_sql(
                f'CREATE TRIGGER "{insert_name}" BEFORE INSERT ON "{table}" '
                f'FOR EACH ROW WHEN EXISTS (SELECT 1 FROM "{table}" WHERE {matches}) BEGIN '
                f"SELECT RAISE(ABORT, 'CreatorProof: {table} is append-only; "
                "UNIQUE replacement is forbidden'); END"
            )
