"""Durable scan orchestration.

PostgreSQL is the authority. Redis only transports stable identifiers, so a lost,
duplicated or replayed message cannot change a committed outcome:

* work is published through a transactional outbox, so a queue outage during the
  request cannot lose an accepted scan;
* every expensive stage owns a durable attempt row;
* a lease with a monotonically increasing epoch means a stale worker that wakes
  after expiry is rejected instead of overwriting a newer attempt;
* only typed transient faults are retried.
"""

from __future__ import annotations

import logging
import os
import socket
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.platform import (
    OutboxState,
    RetryClass,
    ScanLifecycleState,
    StageName,
    StageState,
    WorkerClass,
)
from app.observability import METRICS, log_event
from app.services.canonical import canonical_digest

logger = logging.getLogger("creatorproof.orchestration")

TOPIC_SCAN_ACCEPTED = "scan.accepted"

STAGE_PLAN: tuple[tuple[StageName, WorkerClass], ...] = (
    (StageName.EVIDENCE, WorkerClass.CPU),
    (StageName.STATEMENT, WorkerClass.CPU),
    (StageName.PROOF, WorkerClass.PROOF),
    (StageName.NOTIFY, WorkerClass.NOTIFY),
)

_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "unavailable",
    "deadlock",
    "could not serialize",
    "broken pipe",
    "reset by peer",
)


def worker_identity() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


def classify_exception(exc: BaseException) -> RetryClass:
    """Only typed transient faults are retried; invalid input is terminal."""
    from app.models import ImmutableRecordError

    if isinstance(exc, ScanCancelled):
        return RetryClass.CANCELLED
    if isinstance(exc, ImmutableRecordError | AssertionError):
        return RetryClass.INVARIANT_VIOLATION
    if isinstance(exc, ValueError | TypeError | KeyError):
        return RetryClass.TERMINAL
    if isinstance(exc, TimeoutError | ConnectionError | OSError):
        return RetryClass.TRANSIENT
    message = str(exc).lower()
    if any(marker in message for marker in _TRANSIENT_MARKERS):
        return RetryClass.TRANSIENT
    return RetryClass.TERMINAL


class ScanCancelled(RuntimeError):
    """Raised at a cooperative cancellation checkpoint."""


class StaleLeaseError(RuntimeError):
    """Raised when a worker attempts to commit after losing its lease."""


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------


def enqueue_outbox(
    db: Session,
    *,
    tenant_id: str,
    topic: str,
    payload: dict,
) -> str:
    """Add an outbox row. The caller commits it with the business change."""
    from app.models import OutboxEvent

    event = OutboxEvent(tenant_id=tenant_id, topic=topic, payload=payload)
    db.add(event)
    db.flush()
    return event.id


class OutboxDispatcher:
    """Publishes committed outbox rows without a database/queue dual-write gap."""

    def __init__(self, *, session_factory, queue, max_attempts: int = 8, batch_size: int = 32):
        self._session_factory = session_factory
        self._queue = queue
        self._max_attempts = max_attempts
        self._batch_size = batch_size

    def dispatch_once(self) -> int:
        from app.models import OutboxEvent

        db = self._session_factory()
        published = 0
        try:
            now = datetime.now(UTC)
            rows = db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.state == OutboxState.PENDING,
                    OutboxEvent.available_at <= now,
                )
                .order_by(OutboxEvent.created_at)
                .limit(self._batch_size)
                .with_for_update(skip_locked=True)
                if db.get_bind().dialect.name == "postgresql"
                else select(OutboxEvent)
                .where(
                    OutboxEvent.state == OutboxState.PENDING,
                    OutboxEvent.available_at <= now,
                )
                .order_by(OutboxEvent.created_at)
                .limit(self._batch_size)
            ).all()
            for row in rows:
                try:
                    self._queue.publish(row.topic, row.payload)
                except Exception as exc:
                    row.attempts += 1
                    row.last_error = f"{type(exc).__name__}"
                    # Republish later. The scan is already committed, so the work is
                    # never lost even if the transport stays down for a while.
                    row.available_at = datetime.now(UTC) + timedelta(
                        seconds=min(60, 2**row.attempts)
                    )
                    if row.attempts >= self._max_attempts:
                        row.state = OutboxState.FAILED
                        METRICS.increment("creatorproof_outbox_failed_total", topic=row.topic)
                    continue
                row.state = OutboxState.PUBLISHED
                row.published_at = datetime.now(UTC)
                published += 1
                METRICS.increment("creatorproof_outbox_published_total", topic=row.topic)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("outbox_dispatch_failed")
        finally:
            db.close()
        return published

    def pending_count(self) -> int:
        from app.models import OutboxEvent

        db = self._session_factory()
        try:
            return int(
                db.scalar(
                    select(__import__("sqlalchemy").func.count(OutboxEvent.id)).where(
                        OutboxEvent.state == OutboxState.PENDING
                    )
                )
                or 0
            )
        finally:
            db.close()


class OutboxDispatcherThread(threading.Thread):
    def __init__(self, dispatcher: OutboxDispatcher, interval_seconds: float) -> None:
        super().__init__(name="creatorproof-outbox", daemon=True)
        self._dispatcher = dispatcher
        self._interval = interval_seconds
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._dispatcher.dispatch_once()
            except Exception:  # pragma: no cover - defensive
                logger.exception("outbox_thread_iteration_failed")
            self._stop_event.wait(self._interval)

    def stop(self) -> None:
        self._stop_event.set()


# ---------------------------------------------------------------------------
# Stage ledger
# ---------------------------------------------------------------------------


class StageLedger:
    """Durable execution ledger with lease epochs and typed retries."""

    def __init__(self, *, lease_seconds: int, max_attempts: int) -> None:
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts

    def ensure_stages(self, db: Session, scan) -> None:
        from app.models import StageAttempt

        existing = {
            row.stage
            for row in db.scalars(select(StageAttempt).where(StageAttempt.scan_id == scan.id)).all()
        }
        for stage, worker_class in STAGE_PLAN:
            if str(stage) in existing:
                continue
            db.add(
                StageAttempt(
                    tenant_id=scan.tenant_id,
                    scan_id=scan.id,
                    stage=str(stage),
                    worker_class=str(worker_class),
                    state=StageState.PENDING,
                    max_attempts=self.max_attempts,
                )
            )
        db.commit()

    def acquire(self, db: Session, *, scan_id: str, stage: StageName, owner: str) -> int | None:
        """Claim a stage with compare-and-swap. Returns the new lease epoch."""
        from app.models import StageAttempt

        row = db.scalar(
            select(StageAttempt).where(
                StageAttempt.scan_id == scan_id, StageAttempt.stage == str(stage)
            )
        )
        if row is None:
            return None
        now = datetime.now(UTC)
        lease_expired = row.lease_expires_at is not None and _as_utc(row.lease_expires_at) <= now
        claimable = row.state in {
            StageState.PENDING,
            StageState.READY,
            StageState.FAILED_RETRYABLE,
        } or (row.state == StageState.RUNNING and lease_expired)
        if not claimable:
            return None
        if row.attempt >= row.max_attempts and row.state == StageState.FAILED_RETRYABLE:
            self._mark_terminal(db, row, error_code="RETRY_BUDGET_EXHAUSTED")
            return None

        expected_epoch = row.lease_epoch
        new_epoch = expected_epoch + 1
        result = db.execute(
            update(StageAttempt)
            .where(
                StageAttempt.id == row.id,
                StageAttempt.lease_epoch == expected_epoch,
            )
            .values(
                state=StageState.RUNNING,
                attempt=row.attempt + 1,
                lease_epoch=new_epoch,
                lease_owner=owner,
                lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                heartbeat_at=now,
                started_at=row.started_at or now,
                error_code=None,
                retry_class=None,
            )
        )
        db.commit()
        if result.rowcount != 1:
            # Another worker won the compare-and-swap.
            return None
        METRICS.increment("creatorproof_stage_started_total", stage=str(stage))
        return new_epoch

    def heartbeat(self, db: Session, *, scan_id: str, stage: StageName, epoch: int) -> bool:
        from app.models import StageAttempt

        now = datetime.now(UTC)
        result = db.execute(
            update(StageAttempt)
            .where(
                StageAttempt.scan_id == scan_id,
                StageAttempt.stage == str(stage),
                StageAttempt.lease_epoch == epoch,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=self.lease_seconds),
            )
        )
        db.commit()
        return result.rowcount == 1

    def record_progress(
        self,
        db: Session,
        *,
        scan_id: str,
        stage: StageName,
        epoch: int,
        percent: int,
        label: str,
    ) -> None:
        from app.models import StageAttempt

        now = datetime.now(UTC)
        db.execute(
            update(StageAttempt)
            .where(
                StageAttempt.scan_id == scan_id,
                StageAttempt.stage == str(stage),
                StageAttempt.lease_epoch == epoch,
            )
            .values(
                progress_percent=max(0, min(99, int(percent))),
                progress_label=label,
                heartbeat_at=now,
                lease_expires_at=now + timedelta(seconds=self.lease_seconds),
            )
        )
        db.commit()

    def complete(
        self,
        db: Session,
        *,
        scan_id: str,
        stage: StageName,
        epoch: int,
        output: dict | None = None,
        metrics: dict | None = None,
    ) -> None:
        """Commit a stage result. Rejected when the lease epoch has moved on."""
        from app.models import StageAttempt

        digest = canonical_digest(output) if output is not None else None
        result = db.execute(
            update(StageAttempt)
            .where(
                StageAttempt.scan_id == scan_id,
                StageAttempt.stage == str(stage),
                StageAttempt.lease_epoch == epoch,
            )
            .values(
                state=StageState.SUCCEEDED,
                output_digest=digest,
                completed_at=datetime.now(UTC),
                lease_owner=None,
                lease_expires_at=None,
                metrics=metrics or {},
                # A finished stage reads as finished. Leaving the last in-flight
                # percentage behind makes a completed timeline look stalled.
                progress_percent=100,
            )
        )
        db.commit()
        if result.rowcount != 1:
            raise StaleLeaseError(f"{stage} lease epoch {epoch} is no longer current")
        METRICS.increment("creatorproof_stage_succeeded_total", stage=str(stage))

    def fail(
        self,
        db: Session,
        *,
        scan_id: str,
        stage: StageName,
        epoch: int,
        exc: BaseException,
    ) -> RetryClass:
        from app.models import StageAttempt

        retry_class = classify_exception(exc)
        row = db.scalar(
            select(StageAttempt).where(
                StageAttempt.scan_id == scan_id, StageAttempt.stage == str(stage)
            )
        )
        if row is None:
            return retry_class
        retryable = retry_class == RetryClass.TRANSIENT and row.attempt < row.max_attempts
        if retry_class == RetryClass.CANCELLED:
            new_state = StageState.CANCELLED
        elif retryable:
            new_state = StageState.FAILED_RETRYABLE
        else:
            new_state = StageState.FAILED_TERMINAL
        db.execute(
            update(StageAttempt)
            .where(
                StageAttempt.scan_id == scan_id,
                StageAttempt.stage == str(stage),
                StageAttempt.lease_epoch == epoch,
            )
            .values(
                state=new_state,
                retry_class=str(retry_class),
                error_code=f"{type(exc).__name__}",
                completed_at=None if retryable else datetime.now(UTC),
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        db.commit()
        METRICS.increment(
            "creatorproof_stage_failed_total", stage=str(stage), retry_class=str(retry_class)
        )
        return retry_class

    def skip(self, db: Session, *, scan_id: str, stage: StageName, reason: str) -> None:
        from app.models import StageAttempt

        db.execute(
            update(StageAttempt)
            .where(StageAttempt.scan_id == scan_id, StageAttempt.stage == str(stage))
            .values(
                state=StageState.SKIPPED_BY_POLICY,
                error_code=reason,
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()

    def _mark_terminal(self, db: Session, row, *, error_code: str) -> None:
        from app.models import StageAttempt

        db.execute(
            update(StageAttempt)
            .where(StageAttempt.id == row.id)
            .values(
                state=StageState.FAILED_TERMINAL,
                error_code=error_code,
                completed_at=datetime.now(UTC),
            )
        )
        db.commit()

    def reap_expired(self, db: Session) -> int:
        """Return expired leases to a claimable state so no scan is stranded."""
        from app.models import StageAttempt

        now = datetime.now(UTC)
        rows = db.scalars(
            select(StageAttempt).where(
                StageAttempt.state == StageState.RUNNING,
                StageAttempt.lease_expires_at.is_not(None),
                StageAttempt.lease_expires_at <= now,
            )
        ).all()
        reclaimed = 0
        for row in rows:
            exhausted = row.attempt >= row.max_attempts
            db.execute(
                update(StageAttempt)
                .where(StageAttempt.id == row.id, StageAttempt.lease_epoch == row.lease_epoch)
                .values(
                    state=(
                        StageState.FAILED_TERMINAL if exhausted else StageState.FAILED_RETRYABLE
                    ),
                    retry_class=str(RetryClass.TRANSIENT),
                    error_code="LEASE_EXPIRED",
                    lease_owner=None,
                    lease_expires_at=None,
                )
            )
            reclaimed += 1
        if reclaimed:
            db.commit()
            METRICS.increment("creatorproof_stage_lease_reclaimed_total", value=reclaimed)
            log_event(logger, "stage_leases_reclaimed", reclaimed=reclaimed)
        return reclaimed

    def snapshot(self, db: Session, scan_id: str) -> list[dict]:
        from app.models import StageAttempt

        rows = db.scalars(
            select(StageAttempt)
            .where(StageAttempt.scan_id == scan_id)
            .order_by(StageAttempt.created_at)
        ).all()
        return [
            {
                "stage": row.stage,
                "state": row.state,
                "worker_class": row.worker_class,
                "attempt": row.attempt,
                "max_attempts": row.max_attempts,
                "progress_percent": row.progress_percent,
                "progress_label": row.progress_label,
                "error_code": row.error_code,
                "retry_class": row.retry_class,
                "output_digest": row.output_digest,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            }
            for row in rows
        ]

    def stage_digests(self, db: Session, scan_id: str) -> dict:
        return {
            item["stage"]: item["output_digest"]
            for item in self.snapshot(db, scan_id)
            if item["output_digest"]
        }


def derive_progress(stages: list[dict]) -> dict | None:
    """Derive user-facing progress from the stage ledger instead of ad hoc writes."""
    running = next((item for item in stages if item["state"] == StageState.RUNNING), None)
    if running is not None:
        return {
            "stage": running["stage"],
            "label": running["progress_label"] or "Working",
            "percent": running["progress_percent"],
        }
    pending = next(
        (
            item
            for item in stages
            if item["state"] in {StageState.PENDING, StageState.READY, StageState.FAILED_RETRYABLE}
        ),
        None,
    )
    if pending is not None:
        return {
            "stage": pending["stage"],
            "label": "Queued",
            "percent": pending["progress_percent"],
        }
    return None


class StageReaperThread(threading.Thread):
    def __init__(self, *, session_factory, ledger: StageLedger, interval_seconds: float) -> None:
        super().__init__(name="creatorproof-stage-reaper", daemon=True)
        self._session_factory = session_factory
        self._ledger = ledger
        self._interval = interval_seconds
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            db = self._session_factory()
            try:
                self._ledger.reap_expired(db)
            except Exception:  # pragma: no cover - defensive
                db.rollback()
                logger.exception("stage_reaper_iteration_failed")
            finally:
                db.close()
            self._stop_event.wait(self._interval)

    def stop(self) -> None:
        self._stop_event.set()


# ---------------------------------------------------------------------------
# Cancellation and lifecycle
# ---------------------------------------------------------------------------


def check_cancelled(db: Session, scan_id: str) -> None:
    """Cooperative cancellation checkpoint, called between expensive operations."""
    from app.models import Scan

    values = db.execute(
        select(Scan.cancel_requested_at, Scan.deadline_at).where(Scan.id == scan_id)
    ).first()
    if values is None:
        return
    cancel_requested_at, deadline_at = values
    if cancel_requested_at is not None:
        raise ScanCancelled("SCAN_CANCELLED_BY_REQUEST")
    if deadline_at is not None and _as_utc(deadline_at) <= datetime.now(UTC):
        raise ScanCancelled("SCAN_DEADLINE_EXCEEDED")


def set_lifecycle(db: Session, scan, state: ScanLifecycleState, *, commit: bool = True) -> None:
    scan.lifecycle_state = str(state)
    if commit:
        db.commit()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
