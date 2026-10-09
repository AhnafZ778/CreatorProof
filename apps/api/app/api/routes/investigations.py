"""Human-supervised investigation assistant endpoints.

The assistant can summarize a completed scan's recorded packet, but it cannot
change scan policy state or send a notice.  Each run and output is tenant
scoped, packet-hash bound, and left pending an explicit human disposition.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.models import AuditEvent, InvestigationOutput, InvestigationRun, Scan
from app.services.aiand import (
    PROMPT_TEMPLATE_VERSION,
    AiAndClient,
    AiAndError,
    InvestigationResult,
    evidence_packet_commitment,
    provider_context_hash,
)
from app.services.model_bundle import canonical_json_digest

router = APIRouter(prefix="/v1/investigations", tags=["investigations"])


class InvestigationDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["ACCEPTED", "EDITED", "REJECTED"]
    edited_summary: str | None = Field(default=None, max_length=12_000)
    edited_notice: dict[str, str] | None = None


def _scan_for_tenant(db: Session, tenant_id: str, scan_id: str) -> Scan:
    scan = db.scalar(select(Scan).where(Scan.id == scan_id, Scan.tenant_id == tenant_id))
    if scan is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return scan


def _packet(scan: Scan) -> dict[str, Any]:
    packet = dict(scan.evidence_packet or {})
    # These scalar fields are already persisted facts, and make an investigation
    # useful even when an older scan has no normalized matrix rows yet.
    packet.setdefault("scan_id", scan.id)
    packet.setdefault("match_status", scan.match_status)
    packet.setdefault("policy_action", scan.policy_action)
    packet.setdefault("reason_codes", list(scan.reason_codes or []))
    packet.setdefault("candidate_sha256", scan.candidate_sha256)
    packet.setdefault("top_match_work_id", scan.top_match_work_id)
    return packet


def _run_read(run: InvestigationRun, output: InvestigationOutput | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema": "creatorproof.investigation.v1",
        "run": {
            "id": run.id,
            "scan_id": run.scan_id,
            "status": run.status,
            "provider": run.provider,
            "model": run.model,
            "prompt_template_version": run.prompt_template_version,
            "evidence_packet_hash": run.evidence_packet_hash,
            "input_hash": run.input_hash,
            "error_code": run.error_code,
            "retry_count": run.retry_count,
            "requested_by": run.requested_by,
            "created_at": run.created_at,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        },
        "output": None,
    }
    if output is not None:
        result["output"] = {
            "id": output.id,
            "run_id": output.run_id,
            "summary": output.summary,
            "evidence_references": output.evidence_references or [],
            "missing_facts": output.missing_facts or [],
            "next_steps": output.next_steps or [],
            "duplicate_groups": output.duplicate_groups or [],
            "factual_notice_draft": output.factual_notice_draft,
            "unsupported_claims": output.unsupported_claims or [],
            "output_hash": output.output_hash,
            "provider": output.provider,
            "model": output.model,
            "human_decision": output.human_decision,
            "human_decision_by": output.human_decision_by,
            "human_decision_at": output.human_decision_at,
            "created_at": output.created_at,
        }
    return result


@router.post("/scans/{scan_id}", status_code=status.HTTP_201_CREATED)
async def investigate_scan(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    scan = _scan_for_tenant(db, auth.tenant_id, scan_id)
    if scan.state != "COMPLETED" or not scan.evidence_packet:
        raise HTTPException(status_code=409, detail="A completed evidence packet is required")
    packet = _packet(scan)
    try:
        packet_hash = evidence_packet_commitment(scan.evidence_packet)
    except AiAndError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    run = InvestigationRun(
        tenant_id=auth.tenant_id,
        scan_id=scan.id,
        status="RUNNING",
        requested_by=auth.principal_id or auth.actor_label,
        provider="aiand",
        model=container.settings.aiand_model,
        prompt_template_version=PROMPT_TEMPLATE_VERSION,
        evidence_packet_hash=packet_hash,
        input_hash=provider_context_hash(packet),
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        generated: InvestigationResult = await AiAndClient(container.settings).investigate(packet)
    except AiAndError as exc:
        run.status = "FAILED"
        run.error_code = "AIAND_UNAVAILABLE"
        run.completed_at = datetime.now(UTC)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": run.error_code, "message": str(exc), "run_id": run.id},
        ) from exc

    run.status = "COMPLETED"
    run.provider = generated.provider
    run.model = generated.model
    run.prompt_template_version = generated.prompt_template_version
    run.input_hash = generated.input_hash
    run.completed_at = datetime.now(UTC)
    payload = generated.payload
    output = InvestigationOutput(
        tenant_id=auth.tenant_id,
        run_id=run.id,
        summary=payload["summary"],
        evidence_references=payload["evidence_references"],
        missing_facts=payload["missing_facts"],
        next_steps=payload["next_steps"],
        duplicate_groups=payload["duplicate_groups"],
        factual_notice_draft=payload["factual_notice_draft"],
        unsupported_claims=payload["unsupported_claims"],
        output_hash=generated.output_hash,
        provider=generated.provider,
        model=generated.model,
    )
    db.add(output)
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            principal_id=auth.principal_id,
            credential_id=auth.credential_id,
            event_type="INVESTIGATION_GENERATED",
            resource_type="investigation",
            resource_id=run.id,
            attributes={
                "scan_id": scan.id,
                "packet_hash": packet_hash,
                "output_hash": generated.output_hash,
            },
        )
    )
    db.commit()
    db.refresh(run)
    db.refresh(output)
    result = _run_read(run, output)
    result["reviews"] = []
    return result


@router.get("/{run_id}")
def get_investigation(
    run_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    run = db.scalar(
        select(InvestigationRun).where(
            InvestigationRun.id == run_id, InvestigationRun.tenant_id == auth.tenant_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    output = db.scalar(
        select(InvestigationOutput).where(
            InvestigationOutput.run_id == run.id,
            InvestigationOutput.tenant_id == auth.tenant_id,
        )
    )
    reviews = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == auth.tenant_id,
            AuditEvent.resource_type == "investigation",
            AuditEvent.resource_id == run.id,
            AuditEvent.event_type == "INVESTIGATION_REVIEWED",
        )
        .order_by(AuditEvent.created_at)
    ).all()
    result = _run_read(run, output)
    result["reviews"] = [
        {"id": row.id, "created_at": row.created_at, "review": row.attributes} for row in reviews
    ]
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            principal_id=auth.principal_id,
            credential_id=auth.credential_id,
            event_type="EVIDENCE_READ",
            resource_type="investigation",
            resource_id=run.id,
            attributes={"scan_id": run.scan_id},
        )
    )
    db.commit()
    return result


@router.post("/{run_id}/decision")
def decide_investigation(
    run_id: str,
    payload: InvestigationDecisionRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    run = db.scalar(
        select(InvestigationRun).where(
            InvestigationRun.id == run_id, InvestigationRun.tenant_id == auth.tenant_id
        )
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Investigation run not found")
    output = db.scalar(
        select(InvestigationOutput).where(
            InvestigationOutput.run_id == run.id,
            InvestigationOutput.tenant_id == auth.tenant_id,
        )
    )
    if output is None or run.status != "COMPLETED":
        raise HTTPException(status_code=409, detail="Investigation output is not ready for review")
    if output.human_decision is not None:
        raise HTTPException(status_code=409, detail="Investigation output already has a decision")
    if payload.decision == "EDITED":
        if not payload.edited_summary and not payload.edited_notice:
            raise HTTPException(
                status_code=422, detail="EDITED requires a changed summary or notice"
            )
    elif payload.edited_summary is not None or payload.edited_notice is not None:
        raise HTTPException(status_code=422, detail="Edits require the EDITED disposition")
    reviewer = auth.principal_id or auth.actor_label
    decided_at = datetime.now(UTC)
    # Compare-and-set protects SQLite as well as PostgreSQL when two operators
    # submit a disposition simultaneously. The second writer gets a conflict.
    decided = db.execute(
        update(InvestigationOutput)
        .where(
            InvestigationOutput.id == output.id,
            InvestigationOutput.tenant_id == auth.tenant_id,
            InvestigationOutput.human_decision.is_(None),
        )
        .values(
            human_decision=payload.decision,
            human_decision_by=reviewer,
            human_decision_at=decided_at,
        )
    )
    if decided.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Investigation output already has a decision")
    # Never overwrite provider content or its hash. Human edits are a distinct,
    # append-only review artifact bound to the original generation.
    review = {
        "decision": payload.decision,
        "reviewer": reviewer,
        "original_output_hash": output.output_hash,
        "edited_summary": payload.edited_summary,
        "edited_notice": payload.edited_notice,
    }
    review["review_hash"] = canonical_json_digest(review)
    db.add(
        AuditEvent(
            tenant_id=auth.tenant_id,
            principal_id=auth.principal_id,
            credential_id=auth.credential_id,
            event_type="INVESTIGATION_REVIEWED",
            resource_type="investigation",
            resource_id=run.id,
            attributes=review,
        )
    )
    db.commit()
    db.refresh(output)
    result = _run_read(run, output)
    result["review"] = review
    return result
