"""Durable orchestration invariants.

These are the properties that make a crash survivable: a stage is owned by one
worker at a time, a worker that wakes up after its lease expired cannot overwrite
a newer attempt, only transient faults are retried, and accepted work is never
lost when the queue is down.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.db import Base, build_database
from app.domain.platform import OutboxState, RetryClass, StageName, StageState
from app.models import OutboxEvent, Scan, StageAttempt, Tenant
from app.services.orchestration import (
    OutboxDispatcher,
    ScanCancelled,
    StageLedger,
    StaleLeaseError,
    classify_exception,
    derive_progress,
    enqueue_outbox,
)


@pytest.fixture
def session_factory(tmp_path):
    database = build_database(
        Settings(environment="test", database_url=f"sqlite:///{tmp_path / 'orchestration.db'}")
    )
    Base.metadata.create_all(database.engine)
    return database.session_factory


@pytest.fixture
def db(session_factory):
    session = session_factory()
    session.add(Tenant(id="tn_test", slug="test-tenant", name="Test tenant"))
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def scan(db):
    row = Scan(
        tenant_id="tn_test",
        idempotency_key="idem-x",
        catalog_id="c",
        intended_use="marketing/social",
        candidate_sha256="0" * 64,
        candidate_phash="f" * 16,
        candidate_storage_key="candidates/x",
        state="QUEUED",
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def ledger():
    return StageLedger(lease_seconds=30, max_attempts=3)


# -- retry classification -----------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (TimeoutError("upstream timed out"), RetryClass.TRANSIENT),
        (ConnectionError("connection reset by peer"), RetryClass.TRANSIENT),
        (RuntimeError("service temporarily unavailable"), RetryClass.TRANSIENT),
        (ValueError("candidate image is not decodable"), RetryClass.TERMINAL),
        (KeyError("missing_field"), RetryClass.TERMINAL),
        (AssertionError("invariant broken"), RetryClass.INVARIANT_VIOLATION),
        (ScanCancelled("cancelled by the caller"), RetryClass.CANCELLED),
    ],
)
def test_only_transient_faults_are_marked_retryable(exc, expected):
    assert classify_exception(exc) is expected


# -- leases -------------------------------------------------------------------


def test_a_second_worker_cannot_claim_a_leased_stage(db, ledger, scan):
    ledger.ensure_stages(db, scan)
    first = ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-a")
    assert first is not None
    assert ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-b") is None


def test_an_expired_lease_can_be_reclaimed_with_a_new_epoch(db, ledger, scan):
    ledger.ensure_stages(db, scan)
    first = ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-a")

    row = db.scalar(
        select(StageAttempt).where(
            StageAttempt.scan_id == scan.id, StageAttempt.stage == str(StageName.EVIDENCE)
        )
    )
    row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    second = ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-b")
    assert second is not None
    assert second > first


def test_a_stale_worker_cannot_commit_over_a_newer_attempt(db, ledger, scan):
    ledger.ensure_stages(db, scan)
    stale_epoch = ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-a")

    row = db.scalar(
        select(StageAttempt).where(
            StageAttempt.scan_id == scan.id, StageAttempt.stage == str(StageName.EVIDENCE)
        )
    )
    row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    fresh_epoch = ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-b")

    with pytest.raises(StaleLeaseError):
        ledger.complete(
            db, scan_id=scan.id, stage=StageName.EVIDENCE, epoch=stale_epoch, output={"a": 1}
        )
    ledger.complete(
        db, scan_id=scan.id, stage=StageName.EVIDENCE, epoch=fresh_epoch, output={"a": 1}
    )
    db.expire_all()
    assert row.state == StageState.SUCCEEDED


def test_completed_stage_reports_full_progress(db, ledger, scan):
    ledger.ensure_stages(db, scan)
    epoch = ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-a")
    ledger.record_progress(
        db, scan_id=scan.id, stage=StageName.EVIDENCE, epoch=epoch, percent=42, label="Halfway"
    )
    ledger.complete(db, scan_id=scan.id, stage=StageName.EVIDENCE, epoch=epoch, output={})

    snapshot = {row["stage"]: row for row in ledger.snapshot(db, scan.id)}
    assert snapshot[str(StageName.EVIDENCE)]["progress_percent"] == 100


def test_identical_output_produces_an_identical_digest(db, ledger, scan, session_factory):
    ledger.ensure_stages(db, scan)
    epoch = ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-a")
    ledger.complete(
        db, scan_id=scan.id, stage=StageName.EVIDENCE, epoch=epoch, output={"b": 2, "a": 1}
    )
    first = ledger.stage_digests(db, scan.id)[str(StageName.EVIDENCE)]

    other = Scan(
        tenant_id="tn_test",
        idempotency_key="idem-y",
        catalog_id="c",
        intended_use="marketing/social",
        candidate_sha256="0" * 64,
        candidate_phash="f" * 16,
        candidate_storage_key="candidates/y",
        state="QUEUED",
    )
    db.add(other)
    db.commit()
    ledger.ensure_stages(db, other)
    epoch = ledger.acquire(db, scan_id=other.id, stage=StageName.EVIDENCE, owner="worker-a")
    ledger.complete(
        db, scan_id=other.id, stage=StageName.EVIDENCE, epoch=epoch, output={"a": 1, "b": 2}
    )
    assert ledger.stage_digests(db, other.id)[str(StageName.EVIDENCE)] == first


def test_progress_is_derived_from_the_running_stage(db, ledger, scan):
    ledger.ensure_stages(db, scan)
    epoch = ledger.acquire(db, scan_id=scan.id, stage=StageName.EVIDENCE, owner="worker-a")
    ledger.record_progress(
        db,
        scan_id=scan.id,
        stage=StageName.EVIDENCE,
        epoch=epoch,
        percent=33,
        label="Comparing candidates",
    )
    progress = derive_progress(ledger.snapshot(db, scan.id))
    assert progress["percent"] == 33
    assert progress["label"] == "Comparing candidates"


# -- outbox -------------------------------------------------------------------


class _BrokenQueue:
    def __init__(self) -> None:
        self.attempts = 0

    def publish(self, topic, payload):
        self.attempts += 1
        raise ConnectionError("queue is down")


class _RecordingQueue:
    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    def publish(self, topic, payload):
        self.published.append((topic, payload))


def test_accepted_work_survives_a_queue_outage(db, session_factory):
    enqueue_outbox(db, tenant_id="tn_test", topic="scan.accepted", payload={"scan_id": "s1"})
    db.commit()

    broken = OutboxDispatcher(session_factory=session_factory, queue=_BrokenQueue())
    assert broken.dispatch_once() == 0
    # The event is still pending: nothing was lost by the transport failing.
    assert broken.pending_count() == 1

    row = db.scalar(select(OutboxEvent))
    db.refresh(row)
    row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()

    queue = _RecordingQueue()
    recovered = OutboxDispatcher(session_factory=session_factory, queue=queue)
    assert recovered.dispatch_once() == 1
    assert queue.published == [("scan.accepted", {"scan_id": "s1"})]
    assert recovered.pending_count() == 0


def test_outbox_gives_up_after_max_attempts_and_says_so(db, session_factory):
    enqueue_outbox(db, tenant_id="tn_test", topic="scan.accepted", payload={"scan_id": "s2"})
    db.commit()

    dispatcher = OutboxDispatcher(
        session_factory=session_factory, queue=_BrokenQueue(), max_attempts=2
    )
    for _ in range(2):
        dispatcher.dispatch_once()
        row = db.scalar(select(OutboxEvent))
        db.refresh(row)
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    row = db.scalar(select(OutboxEvent))
    db.refresh(row)
    assert row.state == OutboxState.FAILED
    assert row.last_error == "ConnectionError"
