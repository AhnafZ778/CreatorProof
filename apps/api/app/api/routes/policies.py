"""Policy version administration and dry-run comparison.

A policy version is immutable. Creating one never re-decides existing scans, and
a dry run is explicitly read-only, so a customer can see how a proposed policy
would have behaved before adopting it.
"""

import hashlib
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.enums import CoverageStatus, MatchStatus, PolicyAction, RightsPath
from app.domain.platform import AuditEventType, CredentialScope
from app.models import Scan
from app.schemas import (
    PolicyCreateRequest,
    PolicyDryRunRead,
    PolicyDryRunRequest,
    PolicyRead,
)
from app.services.audit import record_audit_event
from app.services.blockchain import append_integrity_event, prepare_integrity_event
from app.services.policy_store import collect_rights_facts, evaluate_policy

router = APIRouter(prefix="/v1/policies", tags=["policies"])
logger = logging.getLogger("creatorproof.policies")


@router.post("", response_model=PolicyRead, status_code=status.HTTP_201_CREATED)
def create_policy_version(
    payload: PolicyCreateRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
):
    row = container.policies.create_version(
        db,
        tenant_id=auth.tenant_id,
        policy_key=payload.policy_key,
        description=payload.description,
        rules=payload.rules,
        commit=False,
    )
    integrity_event = prepare_integrity_event(
        db,
        signer=container.signer,
        tenant_id=auth.tenant_id,
        event_type="POLICY_VERSION_CREATED",
        subject_type="policy_version",
        subject_id=row.id,
        attributes={
            "policy_key": row.policy_key,
            "version": row.version,
            "policy_digest_sha256": row.digest_sha256,
            "description_sha256": hashlib.sha256(row.description.encode()).hexdigest(),
            "block_enabled": row.block_enabled,
            "is_default": row.is_default,
            "actor_principal_id": auth.principal_id,
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
        logger.exception("policy_integrity_event_publish_deferred event_id=%s", integrity_event.id)
    record_audit_event(
        db,
        tenant_id=auth.tenant_id,
        event_type=AuditEventType.POLICY_CREATED,
        resource_type="policy_version",
        resource_id=row.id,
        principal_id=auth.principal_id,
        attributes={"policy_key": row.policy_key, "version": row.version},
    )
    return row


@router.get("", response_model=list[PolicyRead])
def list_policy_versions(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
):
    return container.policies.list_versions(db, tenant_id=auth.tenant_id)


@router.post("/dry-run", response_model=PolicyDryRunRead)
def dry_run_policies(
    payload: PolicyDryRunRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> PolicyDryRunRead:
    """Re-evaluate one scan's recorded evidence under other policy versions."""
    scan = db.get(Scan, payload.scan_id)
    if scan is None or scan.tenant_id != auth.tenant_id:
        raise HTTPException(status_code=404, detail="Scan not found")
    packet = scan.evidence_packet or {}
    decision = packet.get("decision") or {}
    scope = packet.get("scope") or {}
    if not decision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This scan has no completed evidence to evaluate",
        )

    rights_facts = collect_rights_facts(
        db,
        tenant_id=auth.tenant_id,
        work_id=scan.top_match_work_id,
        intended_use=scan.intended_use,
    )
    recorded_inputs = decision.get("policy_inputs") or {}
    evidence_baseline = recorded_inputs.get("evidence_baseline") or {}
    baseline_action = evidence_baseline.get("policy_action") or decision.get("policy_action")
    baseline_reason_codes = list(
        evidence_baseline.get("reason_codes") or decision.get("reason_codes") or []
    )
    baseline_rights_path = evidence_baseline.get("rights_path") or RightsPath.NO_LICENSE_INFO
    candidates = payload.policy_version_ids or [
        row.id for row in container.policies.list_versions(db, tenant_id=auth.tenant_id)[:4]
    ]

    evaluations = []
    for policy_version_id in candidates:
        policy = container.policies.get_by_id(
            db, tenant_id=auth.tenant_id, policy_version_id=policy_version_id
        )
        if policy is None:
            evaluations.append(
                {"policy_version_id": policy_version_id, "error": "POLICY_VERSION_NOT_FOUND"}
            )
            continue
        trace = evaluate_policy(
            rules=policy.rules,
            baseline_action=PolicyAction(str(baseline_action)),
            baseline_reason_codes=baseline_reason_codes,
            match_status=MatchStatus(str(decision.get("match_status"))),
            coverage_status=CoverageStatus(str(scope.get("coverage_status", "COMPLETE"))),
            rights_path=RightsPath(str(baseline_rights_path)),
            rights_facts=rights_facts,
            ai_origin_classification=decision.get("synthetic_origin_classification"),
            creator_profile_tier=decision.get("style_evidence_tier"),
            origin_policy_mode=decision.get("synthetic_origin_policy_mode"),
            style_review_recommended=bool(decision.get("style_review_recommended")),
        )
        evaluations.append(
            {
                "policy_version_id": policy.id,
                "policy_key": policy.policy_key,
                "version": policy.version,
                "digest_sha256": policy.digest_sha256,
                "decision_trace": trace,
                "differs_from_recorded": trace["policy_action"]
                != str(decision.get("policy_action")),
            }
        )

    return PolicyDryRunRead(
        scan_id=scan.id,
        recorded_policy_version_id=scan.policy_version_id,
        recorded_policy_action=scan.policy_action,
        evaluations=evaluations,
    )
