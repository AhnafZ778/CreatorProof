"""SQLite SQL cannot bypass append-only and attributable-review contracts."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import Base, build_database
from app.models import (
    AssetVersion,
    CatalogVersion,
    ContributionEvent,
    CorpusSnapshotRecord,
    EvidenceCoverage,
    EvidenceMatrix,
    EvidenceSignal,
    EvidenceStatement,
    IntegrityEvent,
    InvestigationOutput,
    InvestigationRun,
    ModelBundle,
    PolicyVersion,
    ProvenanceIngredient,
    ProvenanceRecord,
    ReviewEvent,
    RightsEvent,
    RightsPolicyVersion,
    Scan,
    ScanInputBinding,
    Tenant,
    TransparencyCheckpoint,
    TransparencyLeaf,
    Work,
    _immutable_tables,
)
from app.sqlite_integrity import SQLITE_IMMUTABLE_TABLES

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module", params=["metadata", "migrations"])
def guarded_engine(request, tmp_path_factory):
    directory = tmp_path_factory.mktemp(f"sqlite-integrity-{request.param}")
    url = f"sqlite:///{directory / 'guarded.db'}"
    database = build_database(Settings(_env_file=None, environment="test", database_url=url))
    if request.param == "metadata":
        Base.metadata.create_all(database.engine)
        # Reopening an existing quick-start schema reconciles guards too.
        Base.metadata.create_all(database.engine)
    else:
        config = Config(str(API_ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(API_ROOT / "migrations"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        command.check(config)
    with Session(database.engine) as db:
        db.add(Tenant(id="tenant-a", slug="guard-a", name="Guard fixture"))
        db.commit()
        db.add(
            Work(
                id="work-a",
                tenant_id="tenant-a",
                catalog_id="fixture",
                title="Owned fixture",
                sha256="1" * 64,
                phash="1" * 16,
                storage_key="private/fixture.png",
            )
        )
        db.add(
            Scan(
                id="scan-a",
                tenant_id="tenant-a",
                idempotency_key="fixture-scan",
                catalog_id="fixture",
                intended_use="editorial",
                candidate_sha256="2" * 64,
                candidate_phash="2" * 16,
            )
        )
        db.commit()
        db.add(
            ProvenanceRecord(
                id="prov-a",
                tenant_id="tenant-a",
                work_id="work-a",
                subject_type="work",
                subject_id="work-a",
                input_sha256="1" * 64,
                provider="fixture",
                status="ABSENT",
            )
        )
        db.add(InvestigationRun(id="run-a", tenant_id="tenant-a", scan_id="scan-a"))
        db.add(
            EvidenceMatrix(
                id="matrix-a",
                tenant_id="tenant-a",
                scan_id="scan-a",
                final_status="INSUFFICIENT_EVIDENCE",
                abstention=True,
            )
        )
        db.commit()
        db.add_all(
            [
                RightsPolicyVersion(
                    tenant_id="tenant-a",
                    work_id="work-a",
                    digest_sha256="3" * 64,
                ),
                ProvenanceIngredient(
                    tenant_id="tenant-a",
                    record_id="prov-a",
                    ingredient_id="ingredient-a",
                ),
                EvidenceSignal(
                    signal_id="signal-a",
                    tenant_id="tenant-a",
                    scan_id="scan-a",
                    matrix_id="matrix-a",
                    lane="COPY",
                    provider="fixture",
                    signal_type="HASH",
                    status="UNAVAILABLE",
                ),
                EvidenceCoverage(
                    tenant_id="tenant-a",
                    scan_id="scan-a",
                    matrix_id="matrix-a",
                    lane="COPY",
                    provider="fixture",
                ),
                ContributionEvent(
                    event_id="event-a",
                    tenant_id="tenant-a",
                    work_id="work-a",
                    sequence=1,
                    actor_type="UNKNOWN",
                    event_type="UNSPECIFIED",
                    event_hash="4" * 64,
                ),
                InvestigationOutput(
                    id="output-a",
                    tenant_id="tenant-a",
                    run_id="run-a",
                    provider="fixture",
                    summary="Evidence requires review",
                    output_hash="5" * 64,
                ),
                AssetVersion(
                    tenant_id="tenant-a",
                    work_id="work-a",
                    sha256="1" * 64,
                    phash="1" * 16,
                    storage_key="private/fixture.png",
                ),
                CatalogVersion(
                    tenant_id="tenant-a",
                    catalog_id="fixture",
                    membership_digest="6" * 64,
                ),
                ModelBundle(lane="COPY", bundle_key="fixture", provider_name="fixture"),
                CorpusSnapshotRecord(
                    tenant_id="tenant-a",
                    scan_id="scan-a",
                    catalog_id="fixture",
                    coverage_status="PARTIAL",
                    digest_sha256="7" * 64,
                ),
                ScanInputBinding(
                    tenant_id="tenant-a",
                    scan_id="scan-a",
                    request_digest="8" * 64,
                    candidate_sha256="2" * 64,
                    catalog_id="fixture",
                    intended_use="editorial",
                ),
                EvidenceStatement(
                    id="statement-a",
                    tenant_id="tenant-a",
                    scan_id="scan-a",
                    payload={"meaning": "original signed evidence"},
                    payload_digest_sha256="9" * 64,
                ),
                IntegrityEvent(
                    tenant_id="tenant-a",
                    event_type="REGISTERED",
                    subject_type="work",
                    subject_id="work-a",
                    payload={},
                    payload_digest_sha256="a" * 64,
                ),
                TransparencyLeaf(
                    log_id="fixture",
                    leaf_index=0,
                    statement_id="statement-a",
                    packet_hash_sha256="9" * 64,
                    leaf_hash_sha256="b" * 64,
                ),
                TransparencyCheckpoint(
                    id="checkpoint-a",
                    log_id="fixture",
                    tree_size=1,
                    root_sha256="c" * 64,
                ),
                RightsEvent(
                    tenant_id="tenant-a",
                    subject_type="work",
                    subject_id="work-a",
                    event_type="ASSERTED",
                ),
                PolicyVersion(
                    tenant_id="tenant-a",
                    policy_key="fixture",
                    digest_sha256="d" * 64,
                ),
                ReviewEvent(tenant_id="tenant-a", case_id="fixture-case", event_type="OPENED"),
            ]
        )
        db.commit()
    yield database.engine
    database.engine.dispose()


def test_sqlite_guard_contract_covers_all_orm_immutable_records():
    assert SQLITE_IMMUTABLE_TABLES == _immutable_tables()


@pytest.mark.parametrize("table", sorted(SQLITE_IMMUTABLE_TABLES))
@pytest.mark.parametrize("operation", ["update", "delete", "replace"])
def test_sqlite_sql_cannot_rewrite_delete_or_replace_immutable_records(
    guarded_engine, table, operation
):
    statements = {
        "update": f"UPDATE \"{table}\" SET created_at = '2030-01-01 00:00:00'",
        "delete": f'DELETE FROM "{table}"',
        "replace": f'INSERT OR REPLACE INTO "{table}" SELECT * FROM "{table}"',
    }
    with guarded_engine.connect() as connection:
        before = connection.exec_driver_sql(f'SELECT * FROM "{table}"').all()
    with pytest.raises(IntegrityError, match="append-only"):
        with guarded_engine.begin() as connection:
            connection.exec_driver_sql(statements[operation])
    with guarded_engine.connect() as connection:
        assert connection.exec_driver_sql(f'SELECT * FROM "{table}"').all() == before


def test_sqlite_review_requires_one_complete_attributable_decision(guarded_engine):
    invalid_changes = (
        "human_decision='ACCEPTED'",
        "human_decision='ACCEPTED',human_decision_by='',human_decision_at=CURRENT_TIMESTAMP",
        "human_decision='ACCEPTED',human_decision_by='reviewer',human_decision_at=CURRENT_TIMESTAMP,"
        "summary='rewritten generated content'",
        "human_decision='AUTO_SEND',human_decision_by='reviewer',human_decision_at=CURRENT_TIMESTAMP",
    )
    for assignment in invalid_changes:
        with pytest.raises(IntegrityError, match="append-only"):
            with guarded_engine.begin() as connection:
                connection.exec_driver_sql(
                    f"UPDATE investigation_outputs SET {assignment} WHERE id='output-a'"
                )
    with guarded_engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE investigation_outputs SET human_decision='EDITED',human_decision_by='reviewer',"
            "human_decision_at=CURRENT_TIMESTAMP WHERE id='output-a'"
        )
        row = connection.execute(
            text("SELECT summary,human_decision,human_decision_by FROM investigation_outputs")
        ).one()
        assert row == ("Evidence requires review", "EDITED", "reviewer")
    with pytest.raises(IntegrityError, match="append-only"):
        with guarded_engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE investigation_outputs SET human_decision='REJECTED' WHERE id='output-a'"
            )


def test_sqlite_checkpoint_accepts_one_external_commitment_only(guarded_engine):
    with guarded_engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE transparency_checkpoints SET external_commitment='{}' WHERE id='checkpoint-a'"
        )
    with pytest.raises(IntegrityError, match="append-only"):
        with guarded_engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE transparency_checkpoints SET external_commitment='{\"replaced\":true}' "
                "WHERE id='checkpoint-a'"
            )


def test_sqlite_statement_status_projection_preserves_signed_content(guarded_engine):
    with guarded_engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE evidence_statements SET status='REVOKED' WHERE id='statement-a'"
        )
    with pytest.raises(IntegrityError, match="append-only"):
        with guarded_engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE evidence_statements SET status='ACTIVE',payload='{}' WHERE id='statement-a'"
            )
    with guarded_engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT payload FROM evidence_statements WHERE id='statement-a'"
            ).scalar_one()
            == '{"meaning": "original signed evidence"}'
        )


def test_sqlite_replace_cannot_destroy_an_alternate_unique_identity(guarded_engine):
    with pytest.raises(IntegrityError, match="UNIQUE replacement"):
        with guarded_engine.begin() as connection:
            connection.exec_driver_sql(
                "INSERT OR REPLACE INTO contribution_events "
                "(event_id,tenant_id,work_id,sequence,actor_type,event_type,description,classification,"
                "input_asset_ids,event_hash,timestamp,created_at) SELECT "
                "'new-event-id',tenant_id,work_id,sequence,actor_type,event_type,description,"
                "classification,input_asset_ids,event_hash,timestamp,created_at "
                "FROM contribution_events"
            )
    with guarded_engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT event_id FROM contribution_events").scalar_one()
            == "event-a"
        )
        assert inspect(connection).has_table("contribution_events")
