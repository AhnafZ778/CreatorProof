import hashlib
import json
import logging
from datetime import UTC, datetime
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.enums import ClaimState, RightsPath
from app.domain.platform import AuditEventType, CredentialScope, DeletionReceiptState, LicenseState
from app.models import AssetVersion, Catalog, Claim, DeletionReceipt, License, Work, new_id
from app.schemas import DeletionReceiptRead, WorkRead
from app.services.ai_index import persist_reference_embedding
from app.services.audit import record_audit_event
from app.services.blockchain import append_integrity_event, prepare_integrity_event
from app.services.canonical import canonical_digest
from app.services.images import decode_image
from app.services.metering import Meter, record_usage
from app.services.policy_store import claim_integrity_projection, license_integrity_projection
from app.services.registration_gate import REFUSAL_CODE, screen_registration_origin
from app.services.storage import work_prefix

router = APIRouter(prefix="/v1/works", tags=["works"])
logger = logging.getLogger("creatorproof.works")


def _allowed_uses(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="allowed_uses must be a JSON array") from exc
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise HTTPException(status_code=400, detail="allowed_uses must be a JSON array of strings")
    return sorted({item.strip() for item in parsed if item.strip()})


def _register_bytes(
    *,
    raw: bytes,
    title: str,
    catalog_id: str,
    auth: AuthContext,
    db: Session,
    container: Container,
    rights_path: RightsPath,
    allowed_uses: list[str],
    claimant: str | None,
    claim_state: ClaimState,
) -> Work:
    """Register one set of bytes as a work, asset version and catalog member."""
    tenant_id = auth.tenant_id
    image = decode_image(
        raw,
        max_bytes=container.settings.max_upload_bytes,
        max_pixels=container.settings.max_image_pixels,
    )
    # Screened before anything is written, so a refused file leaves no work row,
    # no asset version and no bytes in storage.
    origin_gate = screen_registration_origin(container, raw=raw, image=image)
    if not origin_gate.allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": REFUSAL_CODE,
                "message": (
                    f"This file was not added to the protected-work catalog. {origin_gate.reason}"
                ),
                "headline": origin_gate.headline,
                "summary": origin_gate.summary,
                "origin_state": origin_gate.state,
                "classification": origin_gate.classification,
                "evidence_tier": origin_gate.evidence_tier,
                # The measured signal and the line it crossed. Without both, a
                # refusal cannot be argued with.
                "score": origin_gate.score,
                "threshold": origin_gate.threshold,
                # The catalog declines to vouch for the file; it does not conclude
                # anything about who made it. Say so where the refusal is read.
                "boundary": (
                    "This is a decision about what this catalog will vouch for, not a "
                    "determination that a person did not create the work. An AI-origin "
                    "signal is probabilistic and can be contested."
                ),
            },
        )

    fingerprints = container.fingerprints.compute(raw, image)
    work_id = new_id("wrk")
    key = f"references/{tenant_id}/{catalog_id}/{work_id}/source.bin"
    work = Work(
        id=work_id,
        tenant_id=tenant_id,
        catalog_id=catalog_id,
        title=title.strip(),
        sha256=fingerprints.sha256,
        phash=fingerprints.phash,
        storage_key=key,
        rights_path=rights_path,
        allowed_uses=allowed_uses,
        claimant=claimant.strip() if claimant else None,
        claim_state=claim_state,
        origin_assessment=origin_gate.record() if origin_gate.checked else None,
    )
    db.add(work)
    # The immutable asset version records exactly which bytes were registered, so a
    # later scan can bind to a specific media identity rather than a mutable row.
    db.add(
        AssetVersion(
            tenant_id=tenant_id,
            work_id=work_id,
            version=1,
            sha256=fingerprints.sha256,
            phash=fingerprints.phash,
            storage_key=key,
            byte_size=len(raw),
            media_type=image.get_format_mimetype() or "image/unknown"
            if hasattr(image, "get_format_mimetype")
            else "image/unknown",
            width=image.width,
            height=image.height,
        )
    )
    if (
        db.scalar(select(Catalog).where(Catalog.tenant_id == tenant_id, Catalog.slug == catalog_id))
        is None
    ):
        db.add(Catalog(tenant_id=tenant_id, slug=catalog_id, name=catalog_id))

    # Keep the original form contract, but materialize its rights declaration as
    # typed, versioned domain rows. Live scans read only these Claim/License rows;
    # the fields on Work are now a compatibility projection for older clients.
    claim_id: str | None = None
    claim_row: Claim | None = None
    if claimant:
        claim_id = new_id("clm")
        claim_row = Claim(
            id=claim_id,
            tenant_id=tenant_id,
            work_id=work_id,
            claimant_label=claimant.strip(),
            claim_type="AUTHORSHIP",
            state=str(claim_state),
            authority_level="REGISTRATION_DECLARATION",
            effective_from=datetime.now(UTC),
        )
        db.add(claim_row)
    license_id: str | None = None
    license_row: License | None = None
    if rights_path == RightsPath.EXISTING_LICENSE and allowed_uses:
        license_id = new_id("lic")
        license_row = License(
            id=license_id,
            tenant_id=tenant_id,
            work_id=work_id,
            claim_id=claim_id,
            version=1,
            state=str(LicenseState.ACTIVE),
            permitted_uses=allowed_uses,
            prohibited_uses=[],
            effective_from=datetime.now(UTC),
        )
        db.add(license_row)
    db.flush()
    integrity_events = [
        prepare_integrity_event(
            db,
            signer=container.signer,
            tenant_id=tenant_id,
            event_type="WORK_REGISTERED",
            subject_type="work",
            subject_id=work_id,
            attributes={
                "asset_version": 1,
                "catalog_id": catalog_id,
                "title_sha256": hashlib.sha256(title.strip().encode()).hexdigest(),
                "sha256": fingerprints.sha256,
                "phash": fingerprints.phash,
                "byte_size": len(raw),
                "rights_path": str(rights_path),
                "allowed_uses": allowed_uses,
                "legacy_claim_state_assertion": str(claim_state),
                "persisted_claim_id": claim_id,
                "persisted_license_id": license_id,
                "claimant_label_sha256": (
                    hashlib.sha256(claimant.strip().encode()).hexdigest() if claimant else None
                ),
                "rights_metadata_source": "PERSISTED_CLAIM_AND_LICENSE_ROWS",
            },
        )
    ]
    if claim_row is not None:
        projection = claim_integrity_projection(claim_row)
        integrity_events.append(
            prepare_integrity_event(
                db,
                signer=container.signer,
                tenant_id=tenant_id,
                event_type="CLAIM_CREATED",
                subject_type="claim",
                subject_id=claim_row.id,
                attributes={
                    "work_id": work_id,
                    "registration_declaration": True,
                    "assertion_only": claim_row.state == str(ClaimState.ASSERTED),
                    "projection": projection,
                    "projection_digest_sha256": canonical_digest(projection),
                },
            )
        )
    if license_row is not None:
        projection = license_integrity_projection(license_row)
        integrity_events.append(
            prepare_integrity_event(
                db,
                signer=container.signer,
                tenant_id=tenant_id,
                event_type="LICENSE_CREATED",
                subject_type="license",
                subject_id=license_row.id,
                attributes={
                    "work_id": work_id,
                    "registration_declaration": True,
                    "projection": projection,
                    "projection_digest_sha256": canonical_digest(projection),
                },
            )
        )
    ai_embedding_key: str | None = None
    try:
        container.storage.put(key, raw)
        if container.ai_retrieval.available:
            try:
                ai_embedding_key = persist_reference_embedding(container, key, image)
            except Exception:
                # Registration remains available if an optional AI model fails. The scan
                # packet exposes the fallback provider instead of pretending AI was used.
                ai_embedding_key = None
        db.commit()
    except Exception:
        db.rollback()
        container.storage.delete(key)
        container.storage.delete(ai_embedding_key)
        raise
    for integrity_event in integrity_events:
        try:
            append_integrity_event(
                db,
                event=integrity_event,
                transparency=container.transparency,
                blockchain=container.blockchain,
            )
        except Exception:
            # Every signed event was committed atomically with the work. Recovery
            # appends any missing leaf after a crash or transient provider outage.
            logger.exception(
                "work_integrity_event_publish_deferred work_id=%s event_id=%s",
                work_id,
                integrity_event.id,
            )
    record_audit_event(
        db,
        tenant_id=tenant_id,
        event_type=AuditEventType.WORK_REGISTERED,
        resource_type="work",
        resource_id=work_id,
        principal_id=auth.principal_id,
        credential_id=auth.credential_id,
        attributes={"catalog_id": catalog_id, "sha256": fingerprints.sha256},
    )
    record_usage(
        db,
        tenant_id=tenant_id,
        meter=Meter.PROTECTED_ASSET,
        attributes={"catalog_id": catalog_id, "work_id": work_id},
    )
    record_usage(
        db,
        tenant_id=tenant_id,
        meter=Meter.STORAGE_BYTES,
        quantity=len(raw),
        attributes={"catalog_id": catalog_id, "work_id": work_id},
    )
    db.refresh(work)
    return work


@router.post("", response_model=WorkRead, status_code=status.HTTP_201_CREATED)
async def register_work(
    title: Annotated[str, Form(min_length=1, max_length=240)],
    catalog_id: Annotated[str, Form(min_length=1, max_length=120)],
    file: Annotated[UploadFile, File()],
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
    rights_path: Annotated[RightsPath, Form()] = RightsPath.NO_LICENSE_INFO,
    allowed_uses: Annotated[str, Form()] = "[]",
    claimant: Annotated[str | None, Form(max_length=240)] = None,
    claim_state: Annotated[ClaimState, Form()] = ClaimState.ASSERTED,
) -> Work:
    raw = await file.read(container.settings.max_upload_bytes + 1)
    return _register_bytes(
        raw=raw,
        title=title,
        catalog_id=catalog_id,
        auth=auth,
        db=db,
        container=container,
        rights_path=rights_path,
        allowed_uses=_allowed_uses(allowed_uses),
        claimant=claimant,
        claim_state=claim_state,
    )


@router.post("/bulk", status_code=status.HTTP_207_MULTI_STATUS)
async def bulk_register_works(
    catalog_id: Annotated[str, Form(min_length=1, max_length=120)],
    files: Annotated[list[UploadFile], File()],
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
    manifest: Annotated[str, Form()] = "[]",
) -> dict:
    """Import a catalog in one request.

    Each file is registered independently and the response reports per-file
    outcomes, because a partially successful import is the normal case for a
    real catalog and must not be reported as a single opaque failure. The
    manifest is a JSON array of objects keyed by ``filename``; a file without a
    manifest entry falls back to safe defaults rather than being rejected.
    """
    try:
        entries = json.loads(manifest)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="manifest must be JSON") from exc
    if not isinstance(entries, list):
        raise HTTPException(status_code=400, detail="manifest must be a JSON array")
    by_filename = {
        str(entry.get("filename")): entry for entry in entries if isinstance(entry, dict)
    }

    if len(files) > container.settings.bulk_import_max_files:
        raise HTTPException(
            status_code=413,
            detail=(
                f"A bulk import accepts at most "
                f"{container.settings.bulk_import_max_files} files per request."
            ),
        )

    imported: list[dict] = []
    rejected: list[dict] = []
    for upload in files:
        entry = by_filename.get(upload.filename or "", {})
        try:
            raw = await upload.read(container.settings.max_upload_bytes + 1)
            work = _register_bytes(
                raw=raw,
                title=str(entry.get("title") or upload.filename or "Untitled work"),
                catalog_id=catalog_id,
                auth=auth,
                db=db,
                container=container,
                rights_path=RightsPath(entry.get("rights_path") or RightsPath.NO_LICENSE_INFO),
                allowed_uses=sorted(
                    {
                        str(item).strip()
                        for item in (entry.get("allowed_uses") or [])
                        if str(item).strip()
                    }
                ),
                claimant=entry.get("claimant"),
                claim_state=ClaimState(entry.get("claim_state") or ClaimState.ASSERTED),
            )
            imported.append({"filename": upload.filename, "work_id": work.id})
        except HTTPException as exc:
            db.rollback()
            rejected.append({"filename": upload.filename, "reason": str(exc.detail)})
        except Exception as exc:
            db.rollback()
            rejected.append({"filename": upload.filename, "reason": type(exc).__name__})

    return {
        "catalog_id": catalog_id,
        "requested": len(files),
        "imported": imported,
        "rejected": rejected,
        "complete": not rejected,
    }


@router.get("/{work_id}/media")
def get_work_media(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_READ))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Return a registered reference through the authenticated API.

    Reference media is already retained by the registry; this endpoint lets the Evidence
    Microscope render the selected nearest reference after a page reload without embedding
    media bytes in the Evidence Packet.
    """
    work = db.get(Work, work_id)
    if work is None or work.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="Work not found")
    asset_version = db.scalar(
        select(AssetVersion)
        .where(
            AssetVersion.tenant_id == auth.tenant_id,
            AssetVersion.work_id == work.id,
        )
        .order_by(AssetVersion.version.desc())
        .limit(1)
    )
    if asset_version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REFERENCE_ASSET_VERSION_MISSING",
                "message": "The work has no immutable asset version and cannot be served.",
            },
        )
    try:
        raw = container.storage.read(asset_version.storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Registered media object not found") from exc
    if (
        hashlib.sha256(raw).hexdigest() != asset_version.sha256
        or len(raw) != asset_version.byte_size
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REFERENCE_ASSET_INTEGRITY_MISMATCH",
                "message": "Stored media does not match its immutable registered identity.",
                "asset_version_id": asset_version.id,
            },
        )
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
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_READ))],
    db: Annotated[Session, Depends(get_db)],
    catalog_id: str | None = None,
) -> list[Work]:
    stmt = select(Work).where(Work.tenant_id == auth.tenant_id).order_by(Work.created_at.desc())
    if catalog_id:
        stmt = stmt.where(Work.catalog_id == catalog_id)
    return list(db.scalars(stmt))


@router.delete("/{work_id}", response_model=DeletionReceiptRead)
def delete_work(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> DeletionReceipt:
    """Delete a registered work and everything derived from it.

    Source media, thumbnails and embeddings share the work prefix and are removed
    together. The receipt lists what was deleted and what could not be, so a
    partial failure is visible instead of silently assumed to have succeeded.
    """
    work = db.get(Work, work_id)
    if work is None or work.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="Work not found")

    work_catalog_id = work.catalog_id
    work_sha256 = work.sha256

    prefix = work_prefix(auth.tenant_id, work_id)
    legacy_prefix = f"references/{auth.tenant_id}/{work.catalog_id}/{work_id}"
    # Commit a signed deletion intent before crossing the database/object-store
    # transaction boundary. If the process dies after object removal, the work is
    # fail-closed (its immutable media hash cannot be read) and a retry can finish
    # deletion while the durable intent explains why the bytes disappeared.
    receipt = DeletionReceipt(
        tenant_id=auth.tenant_id,
        requested_scope={"work_id": work_id, "prefixes": [prefix, legacy_prefix]},
        state=DeletionReceiptState.REQUESTED,
    )
    db.add(receipt)
    db.flush()
    intent_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="WORK_DELETION_REQUESTED",
        subject_type="work",
        subject_id=work_id,
        attributes={
            "catalog_id": work_catalog_id,
            "registered_sha256": work_sha256,
            "deletion_receipt_id": receipt.id,
            "requested_prefixes": [prefix, legacy_prefix],
            "actor_principal_id": auth.principal_id,
        },
    )
    db.commit()
    try:
        append_integrity_event(
            db,
            event=intent_event,
            transparency=container.transparency,
            blockchain=container.blockchain,
        )
    except Exception:
        logger.exception("work_deletion_intent_publish_deferred work_id=%s", work_id)

    deleted: list[str] = []
    retained: list[dict] = []
    for target in (prefix, legacy_prefix):
        try:
            deleted.extend(container.storage.delete_prefix(target))
        except Exception as exc:
            retained.append({"prefix": target, "reason": type(exc).__name__})

    remaining = []
    for target in (prefix, legacy_prefix):
        try:
            remaining.extend(container.storage.list_prefix(target))
        except Exception:
            continue
    retained.extend({"key": key, "reason": "STILL_PRESENT_AFTER_DELETE"} for key in remaining)

    db.delete(work)
    receipt.state = (
        DeletionReceiptState.COMPLETED
        if not retained
        else DeletionReceiptState.COMPLETED_WITH_EXCEPTIONS
    )
    receipt.objects_deleted = deleted
    receipt.objects_retained = retained
    receipt.verified_at = datetime.now(UTC)
    db.flush()
    integrity_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="WORK_DELETED",
        subject_type="work",
        subject_id=work_id,
        attributes={
            "catalog_id": work_catalog_id,
            "registered_sha256": work_sha256,
            "deletion_receipt_id": receipt.id,
            "deletion_state": str(receipt.state),
            "deleted_object_count": len(deleted),
            "retained_object_count": len(retained),
        },
    )
    db.commit()
    try:
        append_integrity_event(
            db,
            event=integrity_event,
            transparency=container.transparency,
            blockchain=container.blockchain,
        )
    except Exception:
        logger.exception("work_deletion_integrity_event_publish_deferred work_id=%s", work_id)
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.DELETION_REQUESTED,
        resource_type="work",
        resource_id=work_id,
        principal_id=auth.principal_id,
        credential_id=auth.credential_id,
        attributes={"deleted_object_count": len(deleted), "retained": retained},
    )
    db.refresh(receipt)
    return receipt
