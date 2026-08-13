from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, get_tenant_id
from app.container import Container
from app.domain.enums import MatchStatus, PolicyAction, ScanState
from app.domain.scan_contract import normalize_scan_text, scan_request_digest
from app.models import Scan, new_id
from app.schemas import ScanRead
from app.services.images import decode_image

router = APIRouter(prefix="/v1/scans", tags=["scans"])


def _replay_or_conflict(existing: Scan, requested_digest: str) -> Scan:
    if existing.request_digest == requested_digest:
        return existing
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "IDEMPOTENCY_PAYLOAD_MISMATCH",
            "message": "This Idempotency-Key is already bound to a different scan request.",
            "existing_scan_id": existing.id,
            "existing_request_digest": existing.request_digest,
            "requested_request_digest": requested_digest,
        },
    )


@router.post("", response_model=ScanRead, status_code=status.HTTP_202_ACCEPTED)
async def create_scan(
    catalog_id: Annotated[str, Form(min_length=1, max_length=120)],
    intended_use: Annotated[str, Form(min_length=1, max_length=160)],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=8, max_length=160),
    ],
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> Scan:
    raw = await file.read(container.settings.max_upload_bytes + 1)
    image = decode_image(
        raw,
        max_bytes=container.settings.max_upload_bytes,
        max_pixels=container.settings.max_image_pixels,
    )
    fingerprints = container.fingerprints.compute(raw, image)
    normalized_catalog_id = normalize_scan_text(catalog_id)
    normalized_intended_use = normalize_scan_text(intended_use)
    requested_digest = scan_request_digest(
        candidate_sha256=fingerprints.sha256,
        catalog_id=normalized_catalog_id,
        intended_use=normalized_intended_use,
    )
    existing = db.scalar(
        select(Scan).where(
            Scan.tenant_id == tenant_id,
            Scan.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return _replay_or_conflict(existing, requested_digest)

    scan_id = new_id("scn")
    storage_key = f"scans/{tenant_id}/{scan_id}/candidate.bin"
    container.storage.put(storage_key, raw)
    scan = Scan(
        id=scan_id,
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
        catalog_id=normalized_catalog_id,
        intended_use=normalized_intended_use,
        candidate_sha256=fingerprints.sha256,
        candidate_phash=fingerprints.phash,
        candidate_storage_key=storage_key,
        state=ScanState.QUEUED,
    )
    db.add(scan)
    try:
        db.commit()
    except Exception:
        db.rollback()
        container.storage.delete(storage_key)
        duplicate = db.scalar(
            select(Scan).where(
                Scan.tenant_id == tenant_id,
                Scan.idempotency_key == idempotency_key,
            )
        )
        if duplicate is not None:
            return _replay_or_conflict(duplicate, requested_digest)
        raise

    try:
        container.queue.enqueue(scan.id)
    except Exception as exc:
        scan.state = ScanState.FAILED
        scan.match_status = MatchStatus.ERROR
        scan.policy_action = PolicyAction.REVIEW
        scan.error_code = "QUEUE_UNAVAILABLE"
        scan.reason_codes = ["QUEUE_UNAVAILABLE"]
        db.commit()
        raise HTTPException(status_code=503, detail="Scan queue unavailable") from exc

    db.expire_all()
    refreshed = db.get(Scan, scan.id)
    return refreshed or scan


@router.get("/{scan_id}", response_model=ScanRead)
def get_scan(
    scan_id: str,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None or scan.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan
