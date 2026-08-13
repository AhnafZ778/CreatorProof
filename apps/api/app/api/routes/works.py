import json
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, get_tenant_id
from app.container import Container
from app.domain.enums import ClaimState, RightsPath
from app.models import Work, new_id
from app.schemas import WorkRead
from app.services.ai_index import embedding_key, persist_reference_embedding
from app.services.images import decode_image

router = APIRouter(prefix="/v1/works", tags=["works"])


def _allowed_uses(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="allowed_uses must be a JSON array") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise HTTPException(status_code=400, detail="allowed_uses must be a JSON array of strings")
    return sorted({item.strip() for item in parsed if item.strip()})


@router.post("", response_model=WorkRead, status_code=status.HTTP_201_CREATED)
async def register_work(
    title: Annotated[str, Form(min_length=1, max_length=240)],
    catalog_id: Annotated[str, Form(min_length=1, max_length=120)],
    file: Annotated[UploadFile, File()],
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
    rights_path: Annotated[RightsPath, Form()] = RightsPath.NO_LICENSE_INFO,
    allowed_uses: Annotated[str, Form()] = "[]",
    claimant: Annotated[str | None, Form(max_length=240)] = None,
    claim_state: Annotated[ClaimState, Form()] = ClaimState.ASSERTED,
) -> Work:
    raw = await file.read(container.settings.max_upload_bytes + 1)
    image = decode_image(
        raw,
        max_bytes=container.settings.max_upload_bytes,
        max_pixels=container.settings.max_image_pixels,
    )
    fingerprints = container.fingerprints.compute(raw, image)
    work_id = new_id("wrk")
    key = f"references/{tenant_id}/{catalog_id}/{work_id}/source.bin"
    container.storage.put(key, raw)
    ai_embedding_key: str | None = None
    if container.ai_retrieval.available:
        try:
            if persist_reference_embedding(container, key, image):
                ai_embedding_key = embedding_key(key, container.ai_retrieval.name)
        except Exception:
            # Registration remains available if an optional AI model fails. The scan packet
            # will expose the fallback provider instead of pretending AI was used.
            ai_embedding_key = None
    work = Work(
        id=work_id,
        tenant_id=tenant_id,
        catalog_id=catalog_id,
        title=title.strip(),
        sha256=fingerprints.sha256,
        phash=fingerprints.phash,
        storage_key=key,
        rights_path=rights_path,
        allowed_uses=_allowed_uses(allowed_uses),
        claimant=claimant.strip() if claimant else None,
        claim_state=claim_state,
    )
    db.add(work)
    try:
        db.commit()
    except Exception:
        db.rollback()
        container.storage.delete(key)
        container.storage.delete(ai_embedding_key)
        raise
    db.refresh(work)
    return work


@router.get("/{work_id}/media")
def get_work_media(
    work_id: str,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Return a registered reference through the authenticated API.

    Reference media is already retained by the registry; this endpoint lets the Evidence
    Microscope render the selected nearest reference after a page reload without embedding
    media bytes in the Evidence Packet.
    """
    work = db.get(Work, work_id)
    if work is None or work.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Work not found")
    raw = container.storage.read(work.storage_key)
    try:
        with Image.open(BytesIO(raw)) as opened:
            media_type = opened.get_format_mimetype() or "application/octet-stream"
    except Exception:
        media_type = "application/octet-stream"
    return Response(
        content=raw,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("", response_model=list[WorkRead])
def list_works(
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    db: Annotated[Session, Depends(get_db)],
    catalog_id: str | None = None,
) -> list[Work]:
    stmt = select(Work).where(Work.tenant_id == tenant_id).order_by(Work.created_at.desc())
    if catalog_id:
        stmt = stmt.where(Work.catalog_id == catalog_id)
    return list(db.scalars(stmt))
