"""Saved comparisons reuse real scan records and the human review workflow."""

import hashlib
from io import BytesIO
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.api.routes.admin import _detection_read
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.models import ReviewCase, Scan, TakedownDraft, Work
from app.services.case_archive import remove_comparison, save_comparison

router = APIRouter(prefix="/v1/admin/stored-cases", tags=["admin"])
Reader = Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_READ))]
Writer = Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))]
Database = Annotated[Session, Depends(get_db)]
Services = Annotated[Container, Depends(get_container)]


def _case(db, tenant_id, scan_id):
    case = db.scalar(
        select(ReviewCase).where(ReviewCase.tenant_id == tenant_id, ReviewCase.scan_id == scan_id)
    )
    if case is None or not case.archive_record:
        raise HTTPException(404, detail="Stored comparison not found")
    return case


def _read(db, container, case):
    scan = db.scalar(select(Scan).where(Scan.id == case.scan_id, Scan.tenant_id == case.tenant_id))
    if scan is None:
        raise HTTPException(404, detail="Scan not found")
    archive = case.archive_record
    work = db.scalar(
        select(Work).where(
            Work.id == archive["work_id"],
            Work.tenant_id == case.tenant_id,
            Work.deleted_at.is_(None),
        )
    )
    value = _detection_read(db, container, scan).model_dump()
    value.update(
        candidate_media_url=f"/v1/admin/stored-cases/{scan.id}/media/candidate",
        reference_media_url=f"/v1/admin/stored-cases/{scan.id}/media/reference",
        candidate_media_status="available",
        candidate_media_expires_at=None,
        stored_case={
            "saved_at": archive["saved_at"],
            "title": archive["title"],
            "reference_sha256": archive["reference_sha256"],
            **archive.get("context", {}),
        },
    )
    if work is None:
        value.update(
            candidate_media_status="unavailable", candidate_media_url=None, reference_media_url=None
        )
    draft = db.scalar(
        select(TakedownDraft)
        .where(TakedownDraft.tenant_id == case.tenant_id, TakedownDraft.scan_id == scan.id)
        .order_by(TakedownDraft.created_at.desc())
        .limit(1)
    )
    if draft is not None:
        value["prepared_notice"] = {
            "id": draft.id,
            "subject": draft.subject,
            "body": draft.body,
            "jurisdiction": draft.jurisdiction,
            "state": draft.state,
            "generation_provider": draft.generation_provider,
            "generation_model": draft.generation_model,
            "recipient_email": draft.recipient_email,
            "created_at": draft.created_at,
        }
    return value


@router.get("")
def list_stored_cases(
    auth: Reader,
    db: Database,
    container: Services,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    cases = db.scalars(
        select(ReviewCase)
        .where(
            ReviewCase.tenant_id == auth.tenant_id,
            ReviewCase.archive_record["schema"].as_string() == "creatorproof.stored-comparison.v1",
        )
        .order_by(ReviewCase.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return [_read(db, container, case) for case in cases]


@router.post("/{scan_id}")
def store_case(scan_id: str, auth: Writer, db: Database, container: Services):
    scan = db.scalar(select(Scan).where(Scan.id == scan_id, Scan.tenant_id == auth.tenant_id))
    if scan is None:
        raise HTTPException(404, detail="Scan not found")
    try:
        case = save_comparison(container, db, scan, actor=auth.principal_id or "operator")
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    return _read(db, container, case)


@router.delete("/{scan_id}", status_code=204)
def delete_case(scan_id: str, auth: Writer, db: Database, container: Services):
    case = _case(db, auth.tenant_id, scan_id)
    remove_comparison(container, db, case, actor=auth.principal_id or "operator")


@router.get("/{scan_id}/media/{kind}")
def comparison_media(
    scan_id: str,
    kind: Literal["candidate", "reference"],
    auth: Reader,
    db: Database,
    container: Services,
):
    archive = _case(db, auth.tenant_id, scan_id).archive_record
    work = db.scalar(
        select(Work).where(
            Work.id == archive["work_id"],
            Work.tenant_id == auth.tenant_id,
            Work.deleted_at.is_(None),
        )
    )
    if work is None:
        raise HTTPException(404, detail="Registered artwork unavailable")
    try:
        raw = container.storage.read(archive[f"{kind}_key"])
    except FileNotFoundError as exc:
        raise HTTPException(404, detail="Comparison image unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != archive[f"{kind}_sha256"]:
        raise HTTPException(409, detail="COMPARISON_IMAGE_INTEGRITY_MISMATCH")
    with Image.open(BytesIO(raw)) as image:
        content_type = image.get_format_mimetype() or "application/octet-stream"
    return Response(
        raw,
        media_type=content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
