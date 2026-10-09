"""Tenant-scoped, hash-verified comparison files retained for operator review."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import ReviewCase, ReviewEvent, Work
from app.services.retention import candidate_expired


def save_comparison(container, db, scan, *, actor="operator", context=None):
    from app.services.review import open_review_case_if_needed

    if scan.state != "COMPLETED" or scan.match_status != "MATCH_FOUND":
        raise ValueError("Only completed registered-artwork matches can be saved.")
    work = db.scalar(
        select(Work).where(
            Work.id == scan.top_match_work_id,
            Work.tenant_id == scan.tenant_id,
            Work.deleted_at.is_(None),
        )
    )
    if work is None:
        raise ValueError("The matched registered artwork is unavailable.")
    case = db.scalar(
        select(ReviewCase)
        .where(ReviewCase.tenant_id == scan.tenant_id, ReviewCase.scan_id == scan.id)
        .with_for_update()
    )
    if case is not None and case.archive_record:
        return case
    if not scan.candidate_storage_key or candidate_expired(
        scan, container.settings.candidate_retention_seconds
    ):
        raise ValueError("The submitted image has expired or was not retained.")
    candidate = container.storage.read(scan.candidate_storage_key)
    reference = container.storage.read(work.storage_key)
    for raw, digest in ((candidate, scan.candidate_sha256), (reference, work.sha256)):
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("Comparison image integrity verification failed.")
    if case is None:
        case = open_review_case_if_needed(
            db,
            scan,
            signer=container.signer,
            transparency=container.transparency,
            blockchain=getattr(container, "blockchain", None),
        )
    if case is None:
        raise ValueError("No review case is available for this match.")
    prefix = f"case-files/{scan.tenant_id}/{case.id}/"
    for name, raw in (("candidate", candidate), ("reference", reference)):
        container.storage.put_bytes(prefix + name, raw)
    case.archive_record = {
        "schema": "creatorproof.stored-comparison.v1",
        "work_id": work.id,
        "candidate_key": prefix + "candidate",
        "reference_key": prefix + "reference",
        "candidate_sha256": scan.candidate_sha256,
        "reference_sha256": work.sha256,
        "saved_at": datetime.now(UTC).isoformat(),
        "title": work.title,
        "context": context or {},
    }
    db.add(
        ReviewEvent(
            tenant_id=scan.tenant_id,
            case_id=case.id,
            event_type="COMPARISON_SAVED",
            actor_label=actor,
            note="Both comparison images saved for continuing operator review.",
            attributes={"candidate_sha256": scan.candidate_sha256, "reference_sha256": work.sha256},
        )
    )
    db.commit()
    return case


def remove_comparison(container, db, case, *, actor="operator"):
    if not case.archive_record:
        return
    container.storage.delete_prefix(f"case-files/{case.tenant_id}/{case.id}/")
    case.archive_record = None
    db.add(
        ReviewEvent(
            tenant_id=case.tenant_id,
            case_id=case.id,
            event_type="COMPARISON_REMOVED",
            actor_label=actor,
            note="Stored comparison images removed; scan evidence remains.",
        )
    )
    db.commit()
