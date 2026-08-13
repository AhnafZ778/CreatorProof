from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.enums import ScanState
from app.domain.platform import (
    AuditEventType,
    CredentialScope,
    ScanLifecycleState,
    StatementType,
)
from app.domain.scan_contract import normalize_scan_text, scan_request_digest
from app.models import EvidenceStatement, Scan, ScanInputBinding, new_id
from app.observability import METRICS, current_correlation_id
from app.schemas import (
    ScanCancelRequest,
    ScanRead,
    ScanStageTimelineRead,
    StatementStatusRequest,
    StatementVerificationRead,
)
from app.services.audit import record_audit_event
from app.services.images import decode_image
from app.services.metering import Meter, record_usage, retention_tier
from app.services.orchestration import TOPIC_SCAN_ACCEPTED, enqueue_outbox
from app.services.statements import (
    active_statement,
    build_verification_package,
    issue_status_statement,
    latest_statement,
    verify_statement_row,
)

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


def _load_scan(db: Session, scan_id: str, tenant_id: str) -> Scan:
    # Expire cached objects so the next query hits the database.  Without this,
    # SQLAlchemy's identity-map can return stale QUEUED/PROCESSING state from an
    # earlier request when the background worker has already committed COMPLETED
    # in a different session.
    db.expire_all()
    scan = db.get(Scan, scan_id)
    if scan is None or scan.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


def _enforce_daily_quota(db: Session, container: Container, tenant_id: str) -> None:
    limit = container.settings.tenant_scan_quota_per_day
    if limit <= 0:
        return
    since = datetime.now(UTC) - timedelta(days=1)
    used = int(
        db.scalar(
            select(func.count(Scan.id)).where(Scan.tenant_id == tenant_id, Scan.created_at >= since)
        )
        or 0
    )
    if used >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "SCAN_QUOTA_EXCEEDED",
                "message": "The daily scan quota for this organization has been reached.",
                "limit": limit,
                "used": used,
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
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> Scan:
    tenant_id = auth.tenant_id
    _enforce_daily_quota(db, container, tenant_id)
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
    correlation_id = current_correlation_id()
    policy = container.policies.get_active(db, tenant_id=tenant_id)
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
        lifecycle_state=str(ScanLifecycleState.ACCEPTED),
        correlation_id=correlation_id,
        principal_id=auth.principal_id,
        policy_version_id=policy.id if policy is not None else None,
        deadline_at=datetime.now(UTC) + timedelta(seconds=container.settings.scan_deadline_seconds),
    )
    db.add(scan)
    # The input binding and the outbox row are written in the same transaction as
    # the scan. Once the client sees 202 the work is durable, so an API, queue or
    # worker crash can delay the result but cannot lose it.
    db.add(
        ScanInputBinding(
            tenant_id=tenant_id,
            scan_id=scan_id,
            request_digest=requested_digest,
            candidate_sha256=fingerprints.sha256,
            catalog_id=normalized_catalog_id,
            intended_use=normalized_intended_use,
            policy_version_id=policy.id if policy is not None else None,
            requested_capabilities={
                "copy_retrieval_requirement": str(container.settings.copy_retrieval_requirement),
                "origin_policy_mode": str(container.settings.synthetic_policy_mode),
            },
        )
    )
    enqueue_outbox(
        db,
        tenant_id=tenant_id,
        topic=TOPIC_SCAN_ACCEPTED,
        payload={"scan_id": scan_id, "correlation_id": correlation_id},
    )
    try:
        db.commit()
    except Exception:
        db.rollback()
        container.storage.delete_prefix(f"scans/{tenant_id}/{scan_id}")
        duplicate = db.scalar(
            select(Scan).where(
                Scan.tenant_id == tenant_id,
                Scan.idempotency_key == idempotency_key,
            )
        )
        if duplicate is not None:
            return _replay_or_conflict(duplicate, requested_digest)
        raise

    record_audit_event(
        db,
        tenant_id=tenant_id,
        event_type=AuditEventType.SCAN_ACCEPTED,
        resource_type="scan",
        resource_id=scan_id,
        principal_id=auth.principal_id,
        credential_id=auth.credential_id,
        correlation_id=correlation_id,
        attributes={"catalog_id": normalized_catalog_id, "intended_use": normalized_intended_use},
    )
    METRICS.increment("creatorproof_scan_accepted_total")
    record_usage(
        db,
        tenant_id=tenant_id,
        meter=Meter.SCAN,
        scan_id=scan_id,
        attributes={
            "catalog_id": normalized_catalog_id,
            "intended_use": normalized_intended_use,
            "retention_tier": retention_tier(container.settings.candidate_retention_seconds),
        },
    )

    # Publish immediately for responsiveness. The background dispatcher retries
    # anything that does not make it out now, so a transport outage is not fatal.
    if container.outbox is not None:
        container.outbox.dispatch_once()

    db.expire_all()
    refreshed = db.get(Scan, scan.id)
    return refreshed or scan


@router.get("/{scan_id}", response_model=ScanRead)
def get_scan(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> Scan:
    return _load_scan(db, scan_id, auth.tenant_id)


@router.get("/{scan_id}/stages", response_model=ScanStageTimelineRead)
def get_scan_stages(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_READ))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> ScanStageTimelineRead:
    """Truthful stage timeline derived from the durable ledger, not from guesses."""
    scan = _load_scan(db, scan_id, auth.tenant_id)
    return ScanStageTimelineRead(
        scan_id=scan.id,
        lifecycle_state=scan.lifecycle_state,
        state=scan.state,
        correlation_id=scan.correlation_id,
        deadline_at=scan.deadline_at,
        cancel_requested_at=scan.cancel_requested_at,
        stages=container.stage_ledger.snapshot(db, scan.id),
    )


@router.post("/{scan_id}/cancel", response_model=ScanRead)
def cancel_scan(
    scan_id: str,
    payload: ScanCancelRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> Scan:
    """Request cooperative cancellation.

    A scan that already produced a committed result is not rewritten; the caller
    is told the result stands.
    """
    scan = _load_scan(db, scan_id, auth.tenant_id)
    if scan.state in {ScanState.COMPLETED, ScanState.FAILED}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "SCAN_ALREADY_TERMINAL",
                "message": "This scan already reached a terminal state and was not modified.",
                "state": scan.state,
            },
        )
    scan.cancel_requested_at = datetime.now(UTC)
    db.commit()
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.SCAN_CANCELLED,
        resource_type="scan",
        resource_id=scan.id,
        principal_id=auth.principal_id,
        correlation_id=scan.correlation_id,
        reason=payload.reason,
    )
    db.refresh(scan)
    return scan


@router.get("/{scan_id}/statement")
def get_scan_statement(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    scan = _load_scan(db, scan_id, auth.tenant_id)
    statement = latest_statement(db, tenant_id=auth.tenant_id, scan_id=scan.id)
    if statement is None:
        raise HTTPException(status_code=404, detail="No signed statement for this scan yet")
    return {
        "statement_id": statement.id,
        "schema": statement.schema_version,
        "statement_type": statement.statement_type,
        "status": statement.status,
        "payload": statement.payload,
        "payload_digest_sha256": statement.payload_digest_sha256,
        "signature": {
            "alg": statement.signature_alg,
            "kid": statement.signature_kid,
            "signature_b64": statement.signature_b64,
            "cose_sign1_b64": statement.cose_sign1_b64,
        },
    }


@router.get("/{scan_id}/statement/verify", response_model=StatementVerificationRead)
def verify_scan_statement(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> StatementVerificationRead:
    """Server-side convenience check. Offline verification remains authoritative."""
    scan = _load_scan(db, scan_id, auth.tenant_id)
    statement = latest_statement(db, tenant_id=auth.tenant_id, scan_id=scan.id)
    if statement is None:
        raise HTTPException(status_code=404, detail="No signed statement for this scan yet")
    result = verify_statement_row(db, statement)
    return StatementVerificationRead(
        statement_id=statement.id,
        valid=bool(result["valid"]),
        digest_matches=bool(result.get("digest_matches", False)),
        signature_valid=bool(result.get("signature_valid", False)),
        status=statement.status,
        kid=statement.signature_kid,
        reason=result.get("reason"),
        note=(
            "Verification confirms the statement is intact and signed by a known key. "
            "It does not establish that any rights claim is legally correct."
        ),
    )


@router.get("/{scan_id}/verification-package")
def download_verification_package(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_READ))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> Response:
    """Self-contained bundle an auditor can verify without calling this API."""
    scan = _load_scan(db, scan_id, auth.tenant_id)
    statement = latest_statement(db, tenant_id=auth.tenant_id, scan_id=scan.id)
    if statement is None:
        raise HTTPException(status_code=404, detail="No signed statement for this scan yet")
    proof = (scan.evidence_packet or {}).get("proof") or {}
    receipt = proof.get("receipt") or {}
    anchor_conditions_met = receipt.get("anchor_conditions_met")
    if anchor_conditions_met is None:
        anchor_conditions_met = receipt.get("finalized") is True
    if container.settings.proof_require_chain and not (
        proof.get("anchor_status") == "ANCHORED" and anchor_conditions_met
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CHAIN_COMMITMENT_POLICY_NOT_REACHED",
                "message": (
                    "This deployment requires a public-chain commitment that satisfies "
                    f"its {container.settings.eas_finality_policy} acceptance policy."
                ),
                "anchor_status": proof.get("anchor_status"),
            },
        )
    package = build_verification_package(
        db,
        statement,
        signer=container.signer,
        transparency=container.transparency,
        packet=scan.evidence_packet or {},
        settings=container.settings,
    )
    package["proof"] = proof
    import json

    return Response(
        content=json.dumps(package, indent=2, sort_keys=True, default=str),
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f'attachment; filename="creatorproof-verification-{scan.id}.json"'
            )
        },
    )


@router.post("/{scan_id}/statement/status", status_code=status.HTTP_201_CREATED)
def append_statement_status(
    scan_id: str,
    payload: StatementStatusRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Append a correction, dispute, supersession or revocation.

    The referenced statement is never edited. Its historical bytes stay verifiable;
    only its current status changes.
    """
    scan = _load_scan(db, scan_id, auth.tenant_id)
    target = (
        db.get(EvidenceStatement, payload.statement_id)
        if payload.statement_id
        else active_statement(db, tenant_id=auth.tenant_id, scan_id=scan.id)
    )
    if target is None or target.tenant_id != auth.tenant_id or target.scan_id != scan.id:
        raise HTTPException(status_code=404, detail="Statement not found for this scan")
    try:
        statement_type = StatementType(payload.statement_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unsupported statement type") from exc
    if statement_type == StatementType.RESULT:
        raise HTTPException(
            status_code=422, detail="RESULT statements are issued by the scan pipeline"
        )
    try:
        return issue_status_statement(
            db,
            signer=container.signer,
            transparency=container.transparency,
            blockchain=container.blockchain,
            scan=scan,
            previous=target,
            statement_type=statement_type,
            reason=payload.reason,
            actor_label=auth.actor_label,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "STALE_STATEMENT_LINEAGE",
                "message": str(exc),
                "statement_id": target.id,
            },
        ) from exc
    except IntegrityError as exc:
        # The unique predecessor constraint is the final arbiter when two
        # reviewers race after both observing the same active statement.
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "STALE_STATEMENT_LINEAGE",
                "message": "This statement already has a successor.",
                "statement_id": target.id,
            },
        ) from exc
