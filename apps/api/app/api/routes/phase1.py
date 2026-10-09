"""Phase 1 rights, evidence, provenance and public verification APIs.

The routes in this module deliberately expose facts and reproducible evidence
instead of legal conclusions.  They are additive to the existing v1 APIs: the
legacy evidence packet, policy fields and signed statements remain unchanged.
"""

from __future__ import annotations

import hashlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import AuditEventType, CredentialScope
from app.models import ProvenanceRecord, Scan, Work
from app.services.audit import record_audit_event

router = APIRouter(prefix="/v1", tags=["phase1"])


def _audit_provenance(db: Session, auth: AuthContext, record: dict) -> dict:
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.EVIDENCE_READ,
        resource_type=record["subject_type"],
        resource_id=record["subject_id"],
        principal_id=auth.principal_id,
        credential_id=auth.credential_id,
        attributes={"projection": "provenance", "record_id": record["id"]},
    )
    return record


def _tenant_work(db: Session, tenant_id: str, work_id: str) -> Work:
    work = db.get(Work, work_id)
    if work is None or work.tenant_id != tenant_id or work.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Work not found")
    return work


def _tenant_scan(db: Session, tenant_id: str, scan_id: str) -> Scan:
    scan = db.get(Scan, scan_id)
    if scan is None or scan.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


@router.post("/works/{work_id}/provenance/inspect", status_code=status.HTTP_201_CREATED)
def inspect_work_provenance(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    work = _tenant_work(db, auth.tenant_id, work_id)
    return _audit_provenance(
        db,
        auth,
        _inspect_stored_provenance(
            db=db,
            container=container,
            tenant_id=auth.tenant_id,
            subject_type="work",
            subject_id=work.id,
            work_id=work.id,
            scan_id=None,
            storage_key=work.storage_key,
            expected_input_hash=work.sha256,
        ),
    )


@router.get("/works/{work_id}/provenance")
def get_work_provenance(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    work = _tenant_work(db, auth.tenant_id, work_id)
    row = db.scalar(
        select(ProvenanceRecord)
        .where(
            ProvenanceRecord.tenant_id == auth.tenant_id,
            ProvenanceRecord.subject_type == "work",
            ProvenanceRecord.subject_id == work.id,
        )
        .order_by(ProvenanceRecord.created_at.desc())
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No provenance inspection for this work")
    return _audit_provenance(db, auth, _provenance_read(row, db))


@router.post("/scans/{scan_id}/provenance/inspect", status_code=status.HTTP_201_CREATED)
def inspect_scan_provenance(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    scan = _tenant_scan(db, auth.tenant_id, scan_id)
    return _audit_provenance(
        db,
        auth,
        _inspect_stored_provenance(
            db=db,
            container=container,
            tenant_id=auth.tenant_id,
            subject_type="scan",
            subject_id=scan.id,
            work_id=None,
            scan_id=scan.id,
            storage_key=scan.candidate_storage_key,
            expected_input_hash=scan.candidate_sha256,
        ),
    )


def _inspect_stored_provenance(
    *,
    db: Session,
    container: Container,
    tenant_id: str,
    subject_type: str,
    subject_id: str,
    work_id: str | None,
    scan_id: str | None,
    storage_key: str | None,
    expected_input_hash: str,
) -> dict[str, Any]:
    if not storage_key:
        raise HTTPException(status_code=404, detail="Media is not retained")
    try:
        raw = container.storage.read(storage_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Scan media is not retained") from exc
    input_hash = hashlib.sha256(raw).hexdigest()
    if input_hash != expected_input_hash:
        raise HTTPException(status_code=409, detail="SOURCE_IMAGE_INTEGRITY_MISMATCH")
    with container.storage.materialized_path(storage_key, raw=raw) as path:
        evidence = container.provenance.inspect(path)
    from dataclasses import asdict

    from app.services.provenance_records import persist_provenance

    row = persist_provenance(
        db,
        tenant_id=tenant_id,
        subject_type=subject_type,
        subject_id=subject_id,
        input_sha256=input_hash,
        evidence=asdict(evidence),
        provider_status=container.provenance.status(),
        raw=raw,
    )
    db.commit()
    db.refresh(row)
    return _provenance_read(row, db)


def _provenance_read(row, db: Session) -> dict[str, Any]:
    from app.models import ProvenanceIngredient

    ingredients = db.scalars(
        select(ProvenanceIngredient)
        .where(
            ProvenanceIngredient.record_id == row.id,
            ProvenanceIngredient.tenant_id == row.tenant_id,
        )
        .order_by(ProvenanceIngredient.created_at)
    ).all()
    return {
        "id": row.id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "input_sha256": row.input_sha256,
        "provider": row.provider,
        "provider_version": row.provider_version,
        "status": row.status,
        "legacy_status": row.legacy_status,
        "reason_codes": list(row.reason_codes or []),
        "manifest_summary": row.manifest_summary or {},
        "trust_details": row.trust_details or {},
        "metadata_summary": row.metadata_summary or {},
        "error_code": row.error_code,
        "fallback_used": row.fallback_used,
        "ingredients": [
            {
                "index": index,
                "hash": item.ingredient_id,
                "relationship": item.relationship,
                "metadata": item.metadata_summary or {},
            }
            for index, item in enumerate(ingredients)
        ],
        "created_at": row.created_at,
    }


@router.get("/scans/{scan_id}/provenance")
def get_scan_provenance(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    from app.models import ProvenanceRecord

    scan = _tenant_scan(db, auth.tenant_id, scan_id)
    row = db.scalar(
        select(ProvenanceRecord)
        .where(ProvenanceRecord.tenant_id == auth.tenant_id, ProvenanceRecord.subject_id == scan.id)
        .order_by(ProvenanceRecord.created_at.desc())
        .limit(1)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="No provenance inspection for this scan")
    return _audit_provenance(db, auth, _provenance_read(row, db))


@router.get("/scans/{scan_id}/evidence-matrix")
def get_evidence_matrix(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    from app.models import EvidenceCoverage, EvidenceMatrix, EvidenceSignal
    from app.services.evidence_assessment import assess_evidence_packet
    from app.services.evidence_ratings import resolve_assessment_scan

    scan = _tenant_scan(db, auth.tenant_id, scan_id)
    matrix = db.scalar(
        select(EvidenceMatrix)
        .where(EvidenceMatrix.tenant_id == auth.tenant_id, EvidenceMatrix.scan_id == scan.id)
        .order_by(EvidenceMatrix.created_at.desc())
        .limit(1)
    )
    signals = db.scalars(
        select(EvidenceSignal)
        .where(
            EvidenceSignal.tenant_id == auth.tenant_id,
            EvidenceSignal.scan_id == scan.id,
            EvidenceSignal.matrix_id == (matrix.id if matrix else None),
        )
        .order_by(EvidenceSignal.created_at, EvidenceSignal.signal_id)
    ).all()
    coverage = db.scalars(
        select(EvidenceCoverage)
        .where(
            EvidenceCoverage.tenant_id == auth.tenant_id,
            EvidenceCoverage.scan_id == scan.id,
            EvidenceCoverage.matrix_id == (matrix.id if matrix else None),
        )
        .order_by(EvidenceCoverage.created_at)
    ).all()
    if matrix is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EVIDENCE_MATRIX_NOT_FINALIZED",
                "message": "This scan has no finalized evidence matrix.",
            },
        )
    source = resolve_assessment_scan(db, scan)
    assessment_signals = signals
    source_matrix = matrix
    if source.id != scan.id:
        source_matrix = db.scalar(
            select(EvidenceMatrix)
            .where(EvidenceMatrix.tenant_id == auth.tenant_id, EvidenceMatrix.scan_id == source.id)
            .order_by(EvidenceMatrix.created_at.desc())
            .limit(1)
        )
        if source_matrix is not None:
            assessment_signals = db.scalars(
                select(EvidenceSignal).where(
                    EvidenceSignal.tenant_id == auth.tenant_id,
                    EvidenceSignal.scan_id == source.id,
                    EvidenceSignal.matrix_id == source_matrix.id,
                )
            ).all()
        else:
            source, source_matrix = scan, matrix
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.EVIDENCE_READ,
        resource_type="scan",
        resource_id=scan.id,
        principal_id=auth.principal_id,
    )
    return {
        "schema": "creatorproof.evidence-matrix.v1",
        "scan_id": scan.id,
        "matrix_id": matrix.id,
        "version": matrix.version,
        "previous_matrix_id": matrix.previous_matrix_id,
        "final_status": matrix.final_status,
        "abstention": matrix.abstention,
        "abstention_code": matrix.abstention_code,
        "reason": matrix.reason,
        "recommended_action": matrix.recommended_action,
        "legal_conclusion": None,
        "match_status": scan.match_status,
        "copy_region_status": "VALIDATED_COPY"
        if scan.match_status == "MATCH_FOUND"
        else "NO_VALIDATED_COPY_REGION",
        "policy_result": scan.policy_action,
        "assessment": assess_evidence_packet(
            source.evidence_packet or {},
            [_model_dict(item) for item in assessment_signals],
            failed=source_matrix.final_status == "PROVIDER_FAILURE",
        ),
        "assessment_signals": [_model_dict(item) for item in assessment_signals],
        "assessment_source": {
            "scan_id": source.id,
            "matrix_id": source_matrix.id,
            "matrix_version": source_matrix.version,
            "completed_at": source.completed_at,
            "packet_hash_sha256": source_matrix.packet_hash_sha256,
            "refreshed": source.id != scan.id,
        },
        "packet_hash_sha256": matrix.packet_hash_sha256,
        "coverage": matrix.coverage_summary or {},
        "signals": [_model_dict(item) for item in signals],
        "coverage_rows": [_model_dict(item) for item in coverage],
        "persisted": True,
        "created_at": matrix.created_at,
    }


def _model_dict(row) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class MatrixCorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=400)


@router.post("/scans/{scan_id}/evidence-matrix/corrections", status_code=201)
def correct_matrix(
    scan_id: str,
    payload: MatrixCorrectionRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    from app.services.evidence_matrix import persist_evidence_matrix

    scan = _tenant_scan(db, auth.tenant_id, scan_id)
    if scan.state not in {"COMPLETED", "FAILED"}:
        raise HTTPException(status_code=409, detail="Scan has not finalized")
    # Acquire a parent write lock on both SQLite and PostgreSQL before reading
    # the latest version; concurrent corrections cannot create a fork.
    db.execute(
        update(Scan)
        .where(Scan.id == scan.id, Scan.tenant_id == auth.tenant_id)
        .values(state=scan.state)
    )
    packet = scan.evidence_packet or {}
    matrix = persist_evidence_matrix(
        db,
        scan=scan,
        packet=packet,
        failed=scan.state == "FAILED",
        correction_reason=payload.reason,
    )
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type="EVIDENCE_MATRIX_CORRECTED",
        resource_type="scan",
        resource_id=scan.id,
        principal_id=auth.principal_id,
        attributes={"matrix_id": matrix.id, "version": matrix.version, "reason": payload.reason},
        commit=False,
    )
    db.commit()
    return {
        "matrix_id": matrix.id,
        "version": matrix.version,
        "previous_matrix_id": matrix.previous_matrix_id,
        "packet_hash_sha256": matrix.packet_hash_sha256,
    }
