"""Opt-in disposable PostgreSQL migration/RLS/immutability verification.

Creates only uniquely named Docker resources and generated test credentials.
The container is bound to localhost and removed in finally. No configured
database URL or user credentials are read or printed.
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API_ROOT = Path(__file__).resolve().parents[1]


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *arguments], capture_output=True, text=True, timeout=120, check=check
    )


def _config(url: str):
    from alembic.config import Config

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _expected_database_rejection(engine, statement: str, *, tenant: str = "tenant-a") -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    try:
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tenant, true)"), {"tenant": tenant}
            )
            connection.execute(text("SELECT set_config('app.bypass_rls', 'off', true)"))
            connection.exec_driver_sql(statement)
    except DBAPIError:
        return
    raise AssertionError("Database accepted an operation required to be rejected")


def _seed(owner_url: str) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models import (
        ContributionEvent,
        EvidenceSignal,
        InvestigationOutput,
        InvestigationRun,
        Scan,
        Tenant,
        Work,
    )
    from app.services.tenancy import bind_system_context

    engine = create_engine(owner_url)
    with Session(engine) as db:
        bind_system_context(db)
        db.add_all(
            [
                Tenant(id="tenant-a", slug="pg-a", name="Fixture A"),
                Tenant(id="tenant-b", slug="pg-b", name="Fixture B"),
            ]
        )
        db.commit()
        db.add_all(
            [
                Work(
                    id=f"work-{letter}",
                    tenant_id=f"tenant-{letter}",
                    catalog_id="fixture",
                    title="Authorized procedural fixture",
                    sha256=str(index) * 64,
                    phash=str(index) * 16,
                    storage_key=f"private/{letter}.png",
                )
                for index, letter in enumerate("ab", 1)
            ]
        )
        db.add(
            Scan(
                id="scan-a",
                tenant_id="tenant-a",
                idempotency_key="pg-fixture-scan",
                catalog_id="fixture",
                intended_use="editorial",
                candidate_sha256="3" * 64,
                candidate_phash="3" * 16,
            )
        )
        db.commit()
        db.add(
            EvidenceSignal(
                signal_id="signal-a",
                tenant_id="tenant-a",
                scan_id="scan-a",
                lane="COPY",
                provider="fixture",
                signal_type="EXACT_HASH",
                status="SUPPORTED",
            )
        )
        db.add(
            ContributionEvent(
                event_id="event-a",
                tenant_id="tenant-a",
                work_id="work-a",
                sequence=1,
                actor_type="HUMAN",
                event_type="ORIGINAL_SKETCH",
                event_hash="4" * 64,
            )
        )
        db.add(InvestigationRun(id="run-a", tenant_id="tenant-a", scan_id="scan-a"))
        db.commit()
        db.add(
            InvestigationOutput(
                id="output-a",
                tenant_id="tenant-a",
                run_id="run-a",
                provider="fixture",
                summary="Needs human review",
                output_hash="5" * 64,
            )
        )
        db.commit()
    engine.dispose()


def verify_postgres(*, image: str = "postgres:17-alpine") -> dict:
    import psycopg
    from alembic import command
    from fastapi.testclient import TestClient
    from psycopg import sql
    from sqlalchemy import create_engine, text

    from app.core.config import Settings
    from app.db import Base, build_database
    from app.main import create_app

    container_name = f"creatorproof-phase1-verify-{uuid4().hex[:12]}"
    admin_password = secrets.token_urlsafe(32)
    owner_password = secrets.token_urlsafe(32)
    runtime_password = secrets.token_urlsafe(32)
    checks: list[str] = []
    engines = []
    report = {
        "schema": "creatorproof.phase1_postgresql_verification.v1",
        "image": image,
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": checks,
        "credentials": "GENERATED_DISPOSABLE_TEST_CREDENTIALS_NOT_RETAINED",
        "container_removed": False,
        "passed": False,
    }
    try:
        _docker(
            "run",
            "--detach",
            "--rm",
            "--name",
            container_name,
            "--publish",
            "127.0.0.1::5432",
            "--env",
            f"POSTGRES_PASSWORD={admin_password}",
            image,
        )
        for _attempt in range(60):
            if (
                _docker(
                    "exec",
                    container_name,
                    "pg_isready",
                    "--host",
                    "127.0.0.1",
                    "--username",
                    "postgres",
                    check=False,
                ).returncode
                == 0
            ):
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        binding = _docker("port", container_name, "5432/tcp").stdout.strip().splitlines()[0]
        port = int(binding.rsplit(":", 1)[1])
        with psycopg.connect(
            host="127.0.0.1",
            port=port,
            user="postgres",
            password=admin_password,
            dbname="postgres",
            autocommit=True,
        ) as admin:
            report["server_version"] = admin.execute("SHOW server_version").fetchone()[0]
            for name, password in (("cp_owner", owner_password), ("cp_runtime", runtime_password)):
                admin.execute(
                    sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOBYPASSRLS").format(
                        sql.Identifier(name), sql.Literal(password)
                    )
                )
            for database in ("cp_empty", "cp_adoption", "cp_legacy"):
                admin.execute(
                    sql.SQL("CREATE DATABASE {} OWNER cp_owner").format(sql.Identifier(database))
                )
        owner_url = (
            f"postgresql+psycopg://cp_owner:{quote(owner_password)}@127.0.0.1:{port}/cp_empty"
        )
        adoption_url = (
            f"postgresql+psycopg://cp_owner:{quote(owner_password)}@127.0.0.1:{port}/cp_adoption"
        )
        runtime_url = (
            f"postgresql+psycopg://cp_runtime:{quote(runtime_password)}@127.0.0.1:{port}/cp_empty"
        )
        legacy_url = (
            f"postgresql+psycopg://cp_owner:{quote(owner_password)}@127.0.0.1:{port}/cp_legacy"
        )
        command.upgrade(_config(owner_url), "head")
        command.check(_config(owner_url))
        checks.append("EMPTY_DATABASE_ALEMBIC_UPGRADE_AND_NO_SCHEMA_DRIFT")
        command.upgrade(_config(legacy_url), "0006_registration_origin_gate")
        legacy_engine = create_engine(legacy_url)
        engines.append(legacy_engine)
        with legacy_engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(32)"
            )
        command.upgrade(_config(legacy_url), "0009_phase1_rights_evidence_investigation")
        with legacy_engine.begin() as connection:
            connection.exec_driver_sql("SELECT set_config('app.bypass_rls', 'on', true)")
            connection.exec_driver_sql(
                "INSERT INTO tenants (id,slug,name,created_at) "
                "VALUES ('legacy-a','legacy-a','Legacy fixture',now())"
            )
            connection.exec_driver_sql(
                "INSERT INTO works (id,tenant_id,catalog_id,title,sha256,phash,storage_key,"
                "rights_path,allowed_uses,claim_state,created_at) VALUES "
                "('legacy-work','legacy-a','fixture','Legacy fixture',%s,%s,'private/legacy.png',"
                "'NO_LICENSE_INFO','[]','ASSERTED','2026-01-01 00:00:00+00')",
                ("1" * 64, "1" * 16),
            )
            connection.exec_driver_sql(
                "INSERT INTO contribution_events (event_id,tenant_id,work_id,sequence,actor_type,"
                "event_type,description,classification,event_hash,created_at) VALUES "
                "('legacy-event','legacy-a','legacy-work',1,'HUMAN','ORIGINAL_SKETCH',"
                "'Legacy sketch',"
                "'HUMAN_CREATED',%s,'2026-01-01 00:00:00+00')",
                ("2" * 64,),
            )
            connection.exec_driver_sql(
                "INSERT INTO scans (id,tenant_id,idempotency_key,catalog_id,intended_use,"
                "candidate_sha256,candidate_phash,state,anchor_status,reason_codes,created_at) "
                "VALUES ('legacy-scan','legacy-a','legacy-key','fixture','editorial',%s,%s,"
                "'COMPLETE','NOT_REQUESTED','[]',now())",
                ("3" * 64, "3" * 16),
            )
            connection.exec_driver_sql(
                "INSERT INTO evidence_matrices (id,tenant_id,scan_id,matrix_version,"
                "final_status,abstention,coverage_summary,created_at) "
                "VALUES ('legacy-matrix','legacy-a','legacy-scan','evidence_matrix.v1',"
                "'INSUFFICIENT_EVIDENCE',true,'{}',now())"
            )
            connection.exec_driver_sql(
                "INSERT INTO evidence_signals (signal_id,tenant_id,scan_id,lane,provider,"
                "signal_type,status,coverage,reason_codes,artifact_refs,fallback_used,created_at) "
                "VALUES ('legacy-signal','legacy-a','legacy-scan','COPY','fixture','EXACT_HASH',"
                "'UNAVAILABLE','{}','[]','[]',false,now())"
            )
            connection.exec_driver_sql(
                "INSERT INTO evidence_coverages (id,tenant_id,scan_id,lane,provider,"
                "requested_scope,completed_scope,unavailable_scope,reason_codes,created_at) "
                "VALUES ('legacy-coverage','legacy-a','legacy-scan','COPY','fixture',"
                "'{}','{}','{}','[]',now())"
            )
        command.upgrade(_config(legacy_url), "0012_sqlite_database_immutability")
        from sqlalchemy.orm import Session

        from app.models import RightsPolicyVersion, Work
        from app.services.canonical import canonical_digest
        from app.services.rights_passport import policy_integrity_projection
        from app.services.tenancy import bind_system_context

        with Session(legacy_engine) as db:
            bind_system_context(db)
            db.add_all(
                Work(
                    id=f"legacy-{label}",
                    tenant_id="legacy-a",
                    catalog_id="fixture",
                    title=label,
                    sha256="4" * 64,
                    phash="4" * 16,
                    storage_key=f"private/{label}.png",
                    deleted_at=datetime.now(UTC) if label == "deleted" else None,
                )
                for label in ("explicit", "deleted")
            )
            db.commit()
            db.add(
                RightsPolicyVersion(
                    id="legacy-explicit-policy",
                    tenant_id="legacy-a",
                    work_id="legacy-explicit",
                    version=2,
                    permissions={"AI_training_permission": "DENY"},
                    digest_sha256="6" * 64,
                )
            )
            db.commit()
        command.upgrade(_config(legacy_url), "head")
        command.check(_config(legacy_url))
        with legacy_engine.begin() as connection:
            length = connection.exec_driver_sql(
                "SELECT character_maximum_length FROM information_schema.columns "
                "WHERE table_name='alembic_version' AND column_name='version_num'"
            ).scalar_one()
            assert length == 128
            report["alembic_head"] = connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
            connection.exec_driver_sql("SELECT set_config('app.bypass_rls', 'on', true)")
            event = connection.exec_driver_sql(
                "SELECT timestamp,created_at,input_asset_ids FROM contribution_events"
            ).one()
            assert event.timestamp == event.created_at
            assert event.input_asset_ids == []
            for table in ("evidence_signals", "evidence_coverages"):
                assert (
                    connection.exec_driver_sql(f"SELECT matrix_id FROM {table}").scalar_one()
                    == "legacy-matrix"
                )
        checks.append("LEGACY_32_CHARACTER_VERSION_TABLE_UPGRADE_PRESERVES_REVISION_IDENTITIES")
        checks.append("LEGACY_IMMUTABLE_CONTRIBUTION_TIMESTAMP_BACKFILL_AND_NO_SCHEMA_DRIFT")
        checks.append("LEGACY_IMMUTABLE_EVIDENCE_MATRIX_LINKAGE_BACKFILLED_UNDER_FORCED_RLS")
        with Session(legacy_engine) as db:
            bind_system_context(db)
            policies = db.query(RightsPolicyVersion).all()
            assert len(policies) == 2
            baseline = next(row for row in policies if row.work_id == "legacy-work")
            assert set(baseline.permissions.values()) == {"UNKNOWN"}
            assert baseline.creator_assertions["status"] == "UNKNOWN"
            assert baseline.consent_metadata["timestamp"] is None
            assert baseline.revocation_metadata["status"] == "UNKNOWN"
            assert baseline.digest_sha256 == canonical_digest(policy_integrity_projection(baseline))
            explicit = db.get(RightsPolicyVersion, "legacy-explicit-policy")
            assert explicit.version == 2
            assert explicit.permissions == {"AI_training_permission": "DENY"}
            assert explicit.digest_sha256 == "6" * 64
        checks.append(
            "UNKNOWN_RIGHTS_BASELINE_BACKFILL_PRESERVES_EXPLICIT_POLICIES_AND_DELETED_WORKS"
        )
        adoption_engine = create_engine(adoption_url)
        engines.append(adoption_engine)
        Base.metadata.create_all(adoption_engine)
        command.upgrade(_config(adoption_url), "head")
        command.check(_config(adoption_url))
        checks.append("CREATE_ALL_DATABASE_ADOPTION_AND_NO_SCHEMA_DRIFT")
        owner_engine = create_engine(owner_url)
        engines.append(owner_engine)
        with owner_engine.begin() as connection:
            connection.exec_driver_sql("GRANT USAGE ON SCHEMA public TO cp_runtime")
            connection.exec_driver_sql(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cp_runtime"
            )
            connection.exec_driver_sql(
                "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cp_runtime"
            )
        _seed(owner_url)
        runtime_engine = create_engine(runtime_url)
        engines.append(runtime_engine)
        settings = Settings(
            _env_file=None,
            environment="test",
            database_url=runtime_url,
            dev_tenant_id="tenant-a",
            dev_tenant_slug="pg-a",
            enable_postgres_rls=True,
            job_backend="inline",
            storage_provider="local",
            dev_auth_enabled=True,
            dev_api_key="postgres-disposable-fixture-key",
            model_bundle_path=API_ROOT / "model_lab/bundles/creatorproof-runtime-ready-v1.json",
            runtime_lock_path=API_ROOT / "uv.lock",
            synthetic_detector="off",
            c2pa_mode="off",
            visible_ai_marker_mode="off",
            style_provider="diagnostic",
            proof_anchor_mode="none",
            sscd_provider="local",
            sscd_remote_url="",
            statement_signing_private_key_hex="",
            trusted_issuer_key_sha256="",
            bootstrap_api_key="",
            synthetic_policy_mode="INFORMATIONAL",
            copy_retrieval_requirement="BASELINE_ALLOWED",
        )
        database = build_database(settings)
        engines.append(database.engine)
        database.assert_runtime_role_safety(require_rls=True)
        checks.append("NONOWNER_NOSUPERUSER_NOBYPASS_RUNTIME_ROLE_WITH_FORCED_RLS")
        with runtime_engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT count(*) FROM works").scalar_one() == 0
            connection.execute(text("SELECT set_config('app.tenant_id', 'tenant-a', true)"))
            assert connection.exec_driver_sql("SELECT id FROM works").scalars().all() == ["work-a"]
            connection.execute(text("SELECT set_config('app.tenant_id', 'tenant-b', true)"))
            assert connection.exec_driver_sql("SELECT id FROM works").scalars().all() == ["work-b"]
        checks.append("UNBOUND_DENIED_AND_CROSS_TENANT_READ_ISOLATION")
        with database.system_session() as db:
            assert db.execute(text("SELECT count(*) FROM works")).scalar_one() == 2
            db.commit()
            assert db.execute(text("SELECT count(*) FROM works")).scalar_one() == 2
        checks.append("EXPLICIT_SYSTEM_WORKER_OVERRIDE_SURVIVES_COMMIT")
        with runtime_engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.tenant_id', 'tenant-a', true)"))
            changed = (
                connection.exec_driver_sql(
                    "UPDATE works SET title='cross-tenant' WHERE id='work-b' RETURNING id"
                )
                .scalars()
                .all()
            )
            assert changed == []
        checks.append("RLS_HIDES_CROSS_TENANT_UPDATE_TARGET")
        _expected_database_rejection(
            runtime_engine,
            "INSERT INTO investigation_runs "
            "(id,tenant_id,scan_id,status,provider,prompt_template_version,retry_count,created_at) "
            "VALUES ('wrong-tenant-run','tenant-b','scan-a','QUEUED','fixture','v1',0,now())",
        )
        checks.append("RLS_REJECTS_CROSS_TENANT_INSERT")
        _expected_database_rejection(
            runtime_engine,
            "INSERT INTO contribution_events "
            "(event_id,tenant_id,work_id,sequence,actor_type,event_type,description,classification,"
            "input_asset_ids,event_hash,timestamp,created_at) VALUES "
            "('wrong-parent','tenant-a','work-b',1,'HUMAN','ORIGINAL_SKETCH','','UNKNOWN','[]','hash',now(),now())",
        )
        checks.append("COMPOSITE_FOREIGN_KEY_REJECTS_CROSS_TENANT_PARENT")
        for statement in (
            "UPDATE evidence_signals SET status='ERROR' WHERE signal_id='signal-a'",
            "DELETE FROM evidence_signals WHERE signal_id='signal-a'",
            "UPDATE contribution_events SET description='rewrite' WHERE event_id='event-a'",
            "DELETE FROM contribution_events WHERE event_id='event-a'",
            "UPDATE investigation_outputs SET summary='rewritten' WHERE id='output-a'",
            "DELETE FROM investigation_outputs WHERE id='output-a'",
        ):
            _expected_database_rejection(runtime_engine, statement)
        checks.append("DATABASE_TRIGGERS_REJECT_EVIDENCE_AND_GENERATED_CONTENT_MUTATION_AND_DELETE")
        with runtime_engine.begin() as connection:
            connection.execute(text("SELECT set_config('app.tenant_id', 'tenant-a', true)"))
            connection.exec_driver_sql(
                "UPDATE investigation_outputs SET human_decision='ACCEPTED', "
                "human_decision_by='fixture-reviewer', human_decision_at=now() "
                "WHERE id='output-a'"
            )
            assert (
                connection.exec_driver_sql(
                    "SELECT summary FROM investigation_outputs WHERE id='output-a'"
                ).scalar_one()
                == "Needs human review"
            )
        _expected_database_rejection(
            runtime_engine,
            "UPDATE investigation_outputs SET human_decision='REJECTED' WHERE id='output-a'",
        )
        checks.append("ONE_ATTRIBUTABLE_HUMAN_DISPOSITION_WITH_IMMUTABLE_PROVIDER_CONTENT")
        with tempfile.TemporaryDirectory(prefix="creatorproof-pg-runtime-") as directory:
            storage = Path(directory)
            settings = settings.model_copy(
                update={
                    "storage_root": storage / "objects",
                    "proof_log_path": storage / "proof.jsonl",
                    "sscd_model_path": storage / "missing-sscd.pt",
                }
            )
            with TestClient(create_app(settings)) as client:
                response = client.get("/v1/works", headers={"X-API-Key": settings.dev_api_key})
                assert response.status_code == 200
                assert "work-b" not in response.text
            checks.append("APPLICATION_STARTUP_AND_AUTHENTICATED_ROUTE_WITH_RUNTIME_ROLE")
        report["passed"] = True
    finally:
        for engine in engines:
            engine.dispose()
        _docker("rm", "--force", container_name, check=False)
        inspection = _docker("inspect", container_name, check=False)
        report["container_removed"] = inspection.returncode != 0
    if not report["container_removed"]:
        raise RuntimeError("Disposable verification container could not be removed")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="postgres:17-alpine")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = verify_postgres(image=args.image)
    if args.report is not None:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
