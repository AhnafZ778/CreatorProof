from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import app.models  # noqa: F401 - register the entire metadata
from app.db import _RLS_REQUIRED_TABLES, Base
from app.models import (
    ContributionEvent,
    EvidenceSignal,
    ImmutableRecordError,
    InvestigationOutput,
    InvestigationRun,
    RightsPolicyVersion,
    Scan,
    Tenant,
    Work,
)
from app.services.canonical import canonical_digest
from app.services.rights_baseline import is_unknown_rights_baseline
from app.services.rights_passport import (
    PERMISSION_FIELDS,
    PassportDimensions,
    policy_integrity_projection,
)
from app.sqlite_integrity import install_sqlite_integrity_guards

API_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def schema_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all(
            [
                Tenant(id="tenant-a", slug="schema-a", name="Tenant A"),
                Tenant(id="tenant-b", slug="schema-b", name="Tenant B"),
            ]
        )
        db.commit()
        db.add(
            Work(
                id="work-a",
                tenant_id="tenant-a",
                catalog_id="catalog-a",
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
                idempotency_key="schema-scan-a",
                catalog_id="catalog-a",
                intended_use="EDITORIAL",
                candidate_sha256="2" * 64,
                candidate_phash="2" * 16,
            )
        )
        db.commit()
        yield db
    engine.dispose()


def _output(db: Session) -> InvestigationOutput:
    run = InvestigationRun(id="run-a", tenant_id="tenant-a", scan_id="scan-a")
    db.add(run)
    db.commit()
    output = InvestigationOutput(
        id="output-a",
        tenant_id="tenant-a",
        run_id=run.id,
        summary="Evidence requires human review",
        output_hash="3" * 64,
        provider="fixture",
    )
    db.add(output)
    db.commit()
    return output


def test_phase1_references_are_bound_to_the_same_tenant(schema_db):
    row = RightsPolicyVersion(
        tenant_id="tenant-b",
        work_id="work-a",
        version=1,
        digest_sha256="4" * 64,
    )
    schema_db.add(row)
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        schema_db.commit()
    schema_db.rollback()
    schema_db.add(InvestigationRun(tenant_id="tenant-b", scan_id="scan-a"))
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        schema_db.commit()


def test_contribution_sequence_is_unique_positive_and_append_only(schema_db):
    row = ContributionEvent(
        event_id="event-a",
        tenant_id="tenant-a",
        work_id="work-a",
        sequence=1,
        actor_type="HUMAN",
        event_type="ORIGINAL_SKETCH",
        event_hash="5" * 64,
        input_asset_ids=[],
        human_decision="Selected final sketch",
        created_by="reviewer-a",
    )
    schema_db.add(row)
    schema_db.commit()
    schema_db.add(
        ContributionEvent(
            event_id="event-b",
            tenant_id="tenant-a",
            work_id="work-a",
            sequence=1,
            actor_type="HUMAN",
            event_type="MANUAL_EDIT",
            event_hash="6" * 64,
        )
    )
    with pytest.raises(IntegrityError, match="UNIQUE"):
        schema_db.commit()
    schema_db.rollback()
    row.description = "Rewrite previous contribution"
    with pytest.raises(ImmutableRecordError, match="append-only"):
        schema_db.commit()
    schema_db.rollback()
    schema_db.delete(row)
    with pytest.raises(ImmutableRecordError, match="append-only"):
        schema_db.commit()


def test_evidence_signal_contract_persists_timing_and_coverage(schema_db):
    start = datetime.now(UTC)
    row = EvidenceSignal(
        signal_id="signal-a",
        tenant_id="tenant-a",
        scan_id="scan-a",
        lane="COPY",
        provider="fixture",
        signal_type="GEOMETRY",
        status="INCONCLUSIVE",
        confidence=0.4,
        confidence_level="LOW",
        coverage_status="PARTIAL",
        started_at=start,
        completed_at=start + timedelta(seconds=1),
        model_or_rule_identifier="geometry-v1",
        reason_codes=["NO_VALIDATED_COPY_REGION"],
    )
    schema_db.add(row)
    schema_db.commit()
    loaded = schema_db.scalar(
        select(EvidenceSignal).where(EvidenceSignal.signal_id == row.signal_id)
    )
    assert loaded.confidence_level == "LOW"
    assert loaded.coverage_status == "PARTIAL"
    assert loaded.completed_at > loaded.started_at
    assert loaded.model_or_rule_identifier == "geometry-v1"


def test_evidence_signal_rejects_invalid_confidence_and_time(schema_db):
    start = datetime.now(UTC)
    schema_db.add(
        EvidenceSignal(
            signal_id="signal-invalid",
            tenant_id="tenant-a",
            scan_id="scan-a",
            lane="COPY",
            provider="fixture",
            signal_type="GEOMETRY",
            status="INCONCLUSIVE",
            confidence=1.5,
        )
    )
    with pytest.raises(IntegrityError, match="confidence_range"):
        schema_db.commit()
    schema_db.rollback()
    schema_db.add(
        EvidenceSignal(
            signal_id="signal-time",
            tenant_id="tenant-a",
            scan_id="scan-a",
            lane="COPY",
            provider="fixture",
            signal_type="GEOMETRY",
            status="INCONCLUSIVE",
            started_at=start,
            completed_at=start - timedelta(seconds=1),
        )
    )
    with pytest.raises(IntegrityError, match="time_order"):
        schema_db.commit()


def test_investigation_generated_content_cannot_be_rewritten_or_deleted(schema_db):
    output = _output(schema_db)
    output.summary = "Invented replacement content"
    with pytest.raises(ImmutableRecordError, match="content is immutable"):
        schema_db.commit()
    schema_db.rollback()
    schema_db.delete(output)
    with pytest.raises(ImmutableRecordError, match="append-only"):
        schema_db.commit()


def test_investigation_accepts_one_attributable_human_disposition(schema_db):
    output = _output(schema_db)
    output.human_decision = "EDITED"
    output.human_decision_by = "reviewer-a"
    output.human_decision_at = datetime.now(UTC)
    schema_db.commit()
    assert output.summary == "Evidence requires human review"
    assert output.output_hash == "3" * 64
    output.human_decision = "REJECTED"
    with pytest.raises(ImmutableRecordError, match="first attributable"):
        schema_db.commit()


def test_investigation_requires_reviewer_and_decision_time(schema_db):
    output = _output(schema_db)
    output.human_decision = "ACCEPTED"
    with pytest.raises(ImmutableRecordError, match="first attributable"):
        schema_db.commit()


def test_phase1_history_preserves_work_identity_for_tombstone_deletion(schema_db):
    schema_db.add(
        RightsPolicyVersion(
            tenant_id="tenant-a",
            work_id="work-a",
            version=1,
            digest_sha256="4" * 64,
        )
    )
    schema_db.commit()
    work = schema_db.get(Work, "work-a")
    work.deleted_at = datetime.now(UTC)
    schema_db.commit()
    schema_db.delete(work)
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        schema_db.commit()


def test_all_phase1_tenant_tables_are_required_at_runtime():
    required = {
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
    }
    assert required <= _RLS_REQUIRED_TABLES


def test_phase1_contract_migration_upgrades_existing_contribution_history(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'phase1-upgrade.db'}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0009_phase1_rights_evidence_investigation")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO tenants (id, slug, name, created_at) VALUES "
            "('tenant-a', 'migration-a', 'Migration A', '2026-01-01 00:00:00')"
        )
        connection.exec_driver_sql(
            "INSERT INTO works (id, tenant_id, catalog_id, title, sha256, phash, storage_key, "
            "rights_path, allowed_uses, claim_state, created_at) VALUES "
            "('work-a', 'tenant-a', 'catalog-a', 'Fixture', ?, ?, 'private/a.png', "
            "'NO_LICENSE_INFO', '[]', 'ASSERTED', '2026-01-01 00:00:00')",
            ("1" * 64, "1" * 16),
        )
        connection.exec_driver_sql(
            "INSERT INTO contribution_events (event_id, tenant_id, work_id, sequence, actor_type, "
            "event_type, description, classification, event_hash, created_at) VALUES "
            "('event-a', 'tenant-a', 'work-a', 1, 'HUMAN', 'ORIGINAL_SKETCH', 'Sketch', "
            "'HUMAN_CREATED', ?, '2026-01-01 00:00:00')",
            ("2" * 64,),
        )
        install_sqlite_integrity_guards(connection)
    engine.dispose()
    command.upgrade(config, "head")
    command.check(config)
    engine = create_engine(database_url)
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT timestamp, created_at, input_asset_ids FROM contribution_events"
        ).one()
        assert row.timestamp == row.created_at
        assert row.input_asset_ids == "[]"
        assert "deleted_at" in {item["name"] for item in inspect(connection).get_columns("works")}
    engine.dispose()


def test_legacy_works_gain_only_missing_unknown_baseline_without_rewriting_policies(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'baseline-upgrade.db'}"
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "0012_sqlite_database_immutability")
    engine = create_engine(database_url)
    registration_time = datetime(2026, 1, 1, 12, 30, 45, 123456, tzinfo=UTC)
    with Session(engine) as db:
        db.add(Tenant(id="tenant-a", slug="baseline-a", name="Baseline fixture"))
        db.commit()
        db.add_all(
            Work(
                id=f"work-{label}",
                tenant_id="tenant-a",
                catalog_id="fixture",
                title=label,
                sha256="1" * 64,
                phash="1" * 16,
                storage_key=f"private/{label}.png",
                created_at=registration_time,
                deleted_at=datetime.now(UTC) if label == "deleted" else None,
            )
            for label in ("missing", "explicit", "deleted")
        )
        db.commit()
        db.add(
            RightsPolicyVersion(
                id="explicit-policy",
                tenant_id="tenant-a",
                work_id="work-explicit",
                version=3,
                permissions={"AI_training_permission": "DENY"},
                digest_sha256="2" * 64,
            )
        )
        db.commit()
    command.upgrade(config, "head")
    command.check(config)
    with Session(engine) as db:
        rows = db.scalars(select(RightsPolicyVersion)).all()
        assert len(rows) == 2
        baseline = next(row for row in rows if row.work_id == "work-missing")
        assert baseline.version == 1
        assert is_unknown_rights_baseline(baseline)
        assert baseline.permissions == {field: "UNKNOWN" for field in PERMISSION_FIELDS}
        assert baseline.dimensions == PassportDimensions().model_dump(mode="json")
        assert baseline.creator_assertions == {
            "assertion": {},
            "baseline_source": "SYSTEM_REGISTRATION_UNKNOWN",
            "creator_id": None,
            "status": "UNKNOWN",
        }
        assert baseline.consent_metadata == {
            "assertion": {},
            "source": None,
            "status": "UNKNOWN",
            "timestamp": None,
        }
        assert baseline.revocation_metadata == {"status": "UNKNOWN", "timestamp": None}
        assert baseline.created_by_principal_id is None
        assert baseline.digest_sha256 == canonical_digest(policy_integrity_projection(baseline))
        assert baseline.effective_from.replace(tzinfo=UTC) == registration_time
        assert baseline.effective_until is None
        assert baseline.corroboration == []
        explicit = db.get(RightsPolicyVersion, "explicit-policy")
        assert explicit.version == 3
        assert explicit.permissions == {"AI_training_permission": "DENY"}
        assert explicit.digest_sha256 == "2" * 64
    command.upgrade(config, "head")
    with Session(engine) as db:
        assert len(db.scalars(select(RightsPolicyVersion)).all()) == 2
    engine.dispose()
