"""Enforce candidate TTL without deleting finalized evidence or reference works."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.domain.enums import ScanState
from app.domain.platform import DeletionReceiptState
from app.models import DeletionReceipt, Scan
from app.services.tenancy import bind_tenant_context

logger = logging.getLogger("creatorproof.retention")


def candidate_expired(scan, retention_seconds: int, *, now: datetime | None = None) -> bool:
    if scan.state not in {ScanState.COMPLETED, ScanState.FAILED}:
        return False
    timestamp = scan.completed_at or scan.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return (now or datetime.now(UTC)) >= timestamp + timedelta(seconds=max(0, retention_seconds))


def purge_candidate_media(container, db, scan, *, force: bool = False) -> bool:
    if not scan.candidate_storage_key or (
        not force and not candidate_expired(scan, container.settings.candidate_retention_seconds)
    ):
        return False
    prefix = f"scans/{scan.tenant_id}/{scan.id}/"
    try:
        deleted = container.storage.delete_prefix(prefix)
    except Exception as exc:
        logger.warning("candidate_delete_failed scan_id=%s error=%s", scan.id, type(exc).__name__)
        db.add(
            DeletionReceipt(
                tenant_id=scan.tenant_id,
                requested_scope={"scan_id": scan.id, "prefix": prefix},
                state=DeletionReceiptState.FAILED,
                objects_retained=[{"prefix": prefix, "reason": type(exc).__name__}],
            )
        )
        db.commit()
        return False
    # Clear only the operational storage locator. Immutable packet/matrix hashes
    # and provenance summaries survive. Failed deletions retain a retry locator.
    scan.candidate_storage_key = None
    db.add(
        DeletionReceipt(
            tenant_id=scan.tenant_id,
            requested_scope={"scan_id": scan.id, "prefix": prefix},
            state=DeletionReceiptState.COMPLETED,
            objects_deleted=deleted,
            verified_at=datetime.now(UTC),
        )
    )
    db.commit()
    return True


def purge_expired_candidates(container, *, limit: int = 100) -> int:
    db = container.database.system_session()
    try:
        scans = db.scalars(
            select(Scan)
            .where(
                Scan.state.in_([ScanState.COMPLETED, ScanState.FAILED]),
                Scan.candidate_storage_key.is_not(None),
            )
            .order_by(Scan.completed_at, Scan.created_at)
            .limit(limit)
        ).all()
        count = 0
        for scan in scans:
            bind_tenant_context(db, scan.tenant_id)
            count += purge_candidate_media(container, db, scan)
        return count
    finally:
        db.close()


class CandidateRetentionThread(threading.Thread):
    def __init__(self, container, interval_seconds: float = 30.0) -> None:
        super().__init__(name="creatorproof-candidate-retention", daemon=True)
        self.container = container
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()

    def run(self) -> None:
        while not self.stop_event.is_set():
            try:
                purge_expired_candidates(self.container)
            except Exception:
                logger.exception("candidate_retention_sweep_failed")
            self.stop_event.wait(self.interval_seconds)

    def stop(self) -> None:
        self.stop_event.set()
