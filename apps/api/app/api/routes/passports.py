"""Rights passport, factual contribution ledger and redacted public verification."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_any_scope, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.models import (
    AuditEvent,
    Claim,
    ContributionEvent,
    CreatorProfile,
    License,
    Party,
    PublicVerificationToken,
    RightsPolicyVersion,
    Scan,
    Work,
    new_id,
)
from app.services.blockchain import append_integrity_event, prepare_integrity_event
from app.services.canonical import canonical_digest
from app.services.rights_baseline import is_unknown_rights_baseline
from app.services.rights_passport import (
    PERMISSION_FIELDS,
    PermissionValue,
    RightsPolicyPayload,
    ai_txt_export,
    aipref_export,
    c2pa_usage_export,
    export_headers,
    iso,
    policy_integrity_projection,
    policy_state,
    public_asset_id,
    tdm_export,
    utc,
)
from app.services.tenancy import bind_tenant_context

router = APIRouter(prefix="/v1", tags=["rights passports"])
public_router = APIRouter(prefix="/verify", tags=["public verification"])
logger = logging.getLogger("creatorproof.passports")


def _work(db: Session, tenant_id: str, work_id: str, *, lock: bool = False) -> Work:
    query = select(Work).where(
        Work.id == work_id, Work.tenant_id == tenant_id, Work.deleted_at.is_(None)
    )
    if lock:
        query = query.with_for_update()
    work = db.scalar(query)
    if work is None:
        raise HTTPException(status_code=404, detail="Work not found")
    return work


def _scan(db: Session, tenant_id: str, scan_id: str) -> Scan:
    row = db.scalar(select(Scan).where(Scan.id == scan_id, Scan.tenant_id == tenant_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Scan not found")
    return row


def _latest_policy(db: Session, tenant_id: str, work_id: str, version: int | None = None):
    query = select(RightsPolicyVersion).where(
        RightsPolicyVersion.tenant_id == tenant_id, RightsPolicyVersion.work_id == work_id
    )
    if version is not None:
        query = query.where(RightsPolicyVersion.version == version)
    return db.scalar(query.order_by(RightsPolicyVersion.version.desc()).limit(1))


def _audit(
    db: Session,
    auth: AuthContext | None,
    *,
    tenant_id: str,
    event_type: str,
    resource_type: str,
    resource_id: str,
    attributes: dict | None = None,
):
    db.add(
        AuditEvent(
            tenant_id=tenant_id,
            principal_id=auth.principal_id if auth else None,
            credential_id=auth.credential_id if auth else None,
            event_type=event_type,
            resource_type=resource_type,
            resource_id=resource_id,
            attributes=attributes or {},
        )
    )


def _publish(db: Session, container: Container, event) -> None:
    try:
        append_integrity_event(
            db, event=event, transparency=container.transparency, blockchain=container.blockchain
        )
    except Exception:
        # Signed event is durable; the dispatcher will publish it after a
        # transient outage. No request payload is put into this log.
        logger.warning("passport_integrity_publish_deferred event_id=%s", event.id)


def _policy_read(row) -> dict[str, Any]:
    projection = policy_integrity_projection(row)
    assertions = row.creator_assertions or {}
    consent = row.consent_metadata or {}
    revocation = row.revocation_metadata or {}
    return {
        **projection,
        "id": row.id,
        "policy_version": row.version,
        "creator_id": assertions.get("creator_id"),
        **{field: (row.permissions or {}).get(field, "UNKNOWN") for field in PERMISSION_FIELDS},
        **(row.dimensions or {}),
        "creator_assertion_status": assertions.get("status", "UNKNOWN"),
        "corroboration_status": "NOT_INDEPENDENTLY_VERIFIED",
        "consent_status": consent.get("status", "UNKNOWN"),
        "consent_source": consent.get("source"),
        "consent_timestamp": consent.get("timestamp"),
        "revocation_status": revocation.get("status", "UNKNOWN"),
        "revocation_timestamp": revocation.get("timestamp"),
        "state": policy_state(row),
        "digest_sha256": row.digest_sha256,
        "created_at": iso(row.created_at),
        "created_by": row.created_by_principal_id,
    }


def _passport(
    db: Session, *, tenant_id: str, work: Work, version: int | None = None
) -> dict[str, Any]:
    policy = _latest_policy(db, tenant_id, work.id, version)
    if version is not None and policy is None:
        raise HTTPException(status_code=404, detail="Rights policy version not found")
    claims = db.scalars(
        select(Claim)
        .where(Claim.tenant_id == tenant_id, Claim.work_id == work.id)
        .order_by(Claim.created_at, Claim.id)
    ).all()
    licenses = db.scalars(
        select(License)
        .where(License.tenant_id == tenant_id, License.work_id == work.id)
        .order_by(License.version, License.id)
    ).all()
    from app.services.policy_store import _rights_projection_integrity

    integrity = _rights_projection_integrity(
        db, tenant_id=tenant_id, claims=list(claims), licenses=list(licenses)
    )
    verified = [
        row
        for row in claims
        if row.state == "CORROBORATED" and (integrity.get(("claim", row.id)) or {}).get("verified")
    ]
    policy_read = _policy_read(policy) if policy else None
    if policy_read is not None:
        policy_read["corroboration_status"] = (
            "CORROBORATED_CLAIM_RECORDED" if verified else "NOT_INDEPENDENTLY_VERIFIED"
        )
    return {
        "schema": "creatorproof.rights-passport.v1",
        "work_id": work.id,
        "creatorproof_identifier": public_asset_id("work", work.id),
        "title": work.title,
        "registration": {
            "sha256": work.sha256,
            "created_at": iso(work.created_at),
            "claimant_assertion": work.claimant,
            "claim_state_assertion": work.claim_state,
            "rights_path_assertion": work.rights_path,
            "allowed_uses_assertion": list(work.allowed_uses or []),
        },
        "policy": policy_read,
        "evidence": {
            "creator_assertion": policy_read.get("creator_assertions") if policy_read else {},
            "verified_evidence": [
                {"claim_id": row.id, "state": row.state, "authority_level": row.authority_level}
                for row in verified
            ],
            "contract_or_license": [
                {
                    "id": row.id,
                    "state": row.state,
                    "version": row.version,
                    "permitted_uses": row.permitted_uses or [],
                    "prohibited_uses": row.prohibited_uses or [],
                    "territories": row.territories or [],
                    "channels": row.channels or [],
                    "audiences": row.audiences or [],
                    "transformations": row.transformations or [],
                    "effective_from": iso(row.effective_from),
                    "effective_until": iso(row.effective_until),
                    "integrity": integrity.get(("license", row.id)),
                }
                for row in licenses
            ],
            "platform_policy": None,
            "organization_policy": None,
            "legal_conclusion": None,
        },
        "exports": {
            "aipref": aipref_export(policy),
            "c2pa_usage_assertions": c2pa_usage_export(policy),
        },
        "limitations": [
            "Self-declarations are creator assertions, not independently verified ownership.",
            "A machine-readable preference does not automatically prevent misuse "
            "or create a licence.",
            "Detection, permission and legal conclusions are separate; "
            "no legal conclusion is produced.",
        ],
    }


@router.post("/works/{work_id}/rights-policy", status_code=status.HTTP_201_CREATED)
def create_rights_policy(
    work_id: str,
    payload: RightsPolicyPayload,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    work = _work(db, auth.tenant_id, work_id, lock=True)
    if payload.creator_id:
        creator = db.scalar(
            select(CreatorProfile).where(
                CreatorProfile.id == payload.creator_id, CreatorProfile.tenant_id == auth.tenant_id
            )
        ) or db.scalar(
            select(Party).where(Party.id == payload.creator_id, Party.tenant_id == auth.tenant_id)
        )
        if creator is None:
            raise HTTPException(status_code=404, detail="Creator identity not found")
    latest = _latest_policy(db, auth.tenant_id, work.id)
    row = RightsPolicyVersion(
        tenant_id=auth.tenant_id,
        work_id=work.id,
        version=latest.version + 1 if latest else 1,
        permissions=payload.normalized_permissions(),
        dimensions=payload.normalized_dimensions(),
        creator_assertions=payload.assertions(),
        consent_metadata=payload.consent_metadata(),
        revocation_metadata=payload.revocation_metadata(),
        corroboration=[],
        effective_from=utc(payload.effective_from),
        effective_until=utc(payload.effective_until),
        created_by_principal_id=auth.principal_id,
    )
    row.digest_sha256 = canonical_digest(policy_integrity_projection(row))
    db.add(row)
    try:
        db.flush()
        event = prepare_integrity_event(
            db,
            signer=container.signer,
            tenant_id=auth.tenant_id,
            event_type="RIGHTS_POLICY_CREATED",
            subject_type="rights_policy",
            subject_id=row.id,
            attributes={
                "projection": policy_integrity_projection(row),
                "policy_digest_sha256": row.digest_sha256,
            },
        )
        _audit(
            db,
            auth,
            tenant_id=auth.tenant_id,
            event_type="RIGHTS_POLICY_CREATED",
            resource_type="rights_policy",
            resource_id=row.id,
            attributes={
                "work_id": work.id,
                "version": row.version,
                "digest_sha256": row.digest_sha256,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONCURRENT_POLICY_VERSION",
                "message": "The policy changed while this version was being recorded. "
                "Retry with the latest version.",
            },
        ) from exc
    _publish(db, container, event)
    return _passport(db, tenant_id=auth.tenant_id, work=work)


@router.get("/works/{work_id}/rights-policy")
def get_rights_policy(
    work_id: str,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    payload = _passport(db, tenant_id=auth.tenant_id, work=_work(db, auth.tenant_id, work_id))
    response.headers.update(export_headers(payload))
    return {**payload, "export_digest_sha256": canonical_digest(payload)}


@router.get("/works/{work_id}/rights-policy/{version}")
def get_rights_policy_version(
    work_id: str,
    version: int,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    payload = _passport(
        db, tenant_id=auth.tenant_id, work=_work(db, auth.tenant_id, work_id), version=version
    )
    response.headers.update(export_headers(payload))
    return {**payload, "export_digest_sha256": canonical_digest(payload)}


@router.get("/works/{work_id}/ai-preferences")
def get_ai_preferences(
    work_id: str,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    work = _work(db, auth.tenant_id, work_id)
    row = _latest_policy(db, auth.tenant_id, work.id)
    result = {
        "schema": "creatorproof.ai-preferences.v1",
        "work_id": work.id,
        "policy_state": policy_state(row),
        "preferences": row.permissions if row else {key: "UNKNOWN" for key in PERMISSION_FIELDS},
        "dimensions": row.dimensions if row else {},
        "aipref": aipref_export(row),
        "c2pa_usage_assertions": c2pa_usage_export(row),
        "creatorproof_identifier": public_asset_id("work", work.id),
    }
    response.headers.update(export_headers(result))
    return result


@router.get("/works/{work_id}/ai.txt")
def get_ai_txt(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    work = _work(db, auth.tenant_id, work_id)
    body = ai_txt_export(_latest_policy(db, auth.tenant_id, work.id), work_id=work.id)
    return Response(body, media_type="text/plain", headers=export_headers(body))


@router.get("/works/{work_id}/tdm-policy")
def get_tdm_policy(
    work_id: str,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    work = _work(db, auth.tenant_id, work_id)
    row = _latest_policy(db, auth.tenant_id, work.id)
    payload = tdm_export(row, work_id=work.id)
    payload["policy_identifier"] = (
        f"urn:creatorproof:rights-policy:{row.id}" if row else f"urn:creatorproof:work:{work.id}"
    )
    # A URN identifies this internal export. It is not falsely advertised as a
    # discoverable HTTP tdm-policy URL on an unconfigured publisher origin.
    payload["deployment_required"] = (
        "Publish this export and its reservation header on the content origin; "
        "the authenticated API is not a public discovery endpoint."
    )
    response.headers.update(export_headers(payload))
    return payload


@router.get("/works/{work_id}/rights-statement")
def get_rights_statement(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.RIGHTS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    work = _work(db, auth.tenant_id, work_id)
    row = _latest_policy(db, auth.tenant_id, work.id)
    lines = [
        f"CreatorProof rights statement for {work.id}",
        f"Policy state: {policy_state(row)}",
        "Recorded preferences:",
    ]
    lines += (
        [f"{key}: {(row.permissions or {}).get(key, 'UNKNOWN')}" for key in PERMISSION_FIELDS]
        if row
        else ["No rights preferences recorded."]
    )
    lines += [
        "This is a creator preference record. It does not establish ownership, "
        "grant a licence, or determine infringement."
    ]
    body = "\n".join(lines) + "\n"
    return Response(body, media_type="text/plain", headers=export_headers(body))


class ContributionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    action_type: Literal[
        "ORIGINAL_CAPTURE",
        "ORIGINAL_SKETCH",
        "MANUAL_EDIT",
        "AI_GENERATION",
        "AI_EDIT",
        "AI_UPSCALE",
        "AI_BACKGROUND_REMOVAL",
        "HUMAN_SELECTION",
        "HUMAN_COMPOSITION",
        "COLOR_CORRECTION",
        "CROPPING",
        "EXPORT",
        "PUBLICATION",
        "LICENSED_SOURCE_IMPORT",
    ] = Field(validation_alias=AliasChoices("action_type", "event_type"))
    description: str = Field(min_length=1, max_length=4000)
    classification: Literal[
        "HUMAN_CREATED",
        "AI_ASSISTED_SUBSTANTIAL",
        "AI_GENERATED_HUMAN_SELECTION",
        "AI_GENERATED_MINOR_MODIFICATION",
        "UNKNOWN",
    ] = "UNKNOWN"
    actor_type: Literal["HUMAN", "AI", "SYSTEM", "UNKNOWN"] = "UNKNOWN"
    actor_id: str | None = Field(default=None, max_length=160)
    input_asset_ids: list[str] = Field(default_factory=list, max_length=100)
    output_asset_id: str | None = Field(default=None, max_length=96)
    software_or_model: str | None = Field(default=None, max_length=240)
    model_provider: str | None = Field(default=None, max_length=120)
    model_version: str | None = Field(default=None, max_length=160)
    input_hash: str | None = Field(
        default=None,
        pattern=r"^[a-fA-F0-9]{64}$",
        validation_alias=AliasChoices("input_hash", "hash_before"),
    )
    output_hash: str | None = Field(
        default=None,
        pattern=r"^[a-fA-F0-9]{64}$",
        validation_alias=AliasChoices("output_hash", "hash_after"),
    )
    prompt_reference: str | None = Field(
        default=None,
        max_length=256,
        pattern=r"^(?:sha256:[a-fA-F0-9]{64}|[A-Za-z0-9_.:/-]{1,256})$",
    )
    human_decision: str | None = Field(default=None, max_length=1000)
    timestamp: datetime | None = None
    evidence_artifact_reference: str | None = Field(default=None, max_length=512)
    c2pa_reference: str | None = Field(default=None, max_length=512)
    source_reference: str | None = Field(default=None, max_length=512)

    @field_validator("input_asset_ids")
    @classmethod
    def asset_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 96 for value in values):
            raise ValueError("Input asset IDs must be nonempty and bounded")
        return sorted(set(values))


def _contribution_projection(row) -> dict[str, Any]:
    return {
        "schema": "creatorproof.contribution-event.v2",
        "event_id": row.event_id,
        "work_id": row.work_id,
        "sequence": row.sequence,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "action_type": row.event_type,
        "description": row.description,
        "classification": row.classification,
        "provider": row.provider,
        "model": row.model,
        "input_hash": row.input_hash,
        "output_hash": row.output_hash,
        "prompt_reference": row.prompt_reference,
        "source_reference": row.source_reference,
        "input_asset_ids": row.input_asset_ids or [],
        "output_asset_id": row.output_asset_id,
        "software_or_model": row.software_or_model,
        "human_decision": row.human_decision,
        "timestamp": iso(row.timestamp),
        "evidence_artifact_reference": row.evidence_artifact_reference,
        "c2pa_reference": row.c2pa_reference,
        "previous_event_hash": row.previous_event_hash,
        "created_by": row.created_by,
        "created_at": iso(row.created_at),
    }


def _contribution_read(row) -> dict[str, Any]:
    return {
        **_contribution_projection(row),
        "event_hash": row.event_hash,
        "hash_before": row.input_hash,
        "hash_after": row.output_hash,
    }


@router.post("/works/{work_id}/contributions", status_code=status.HTTP_201_CREATED)
def append_contribution(
    work_id: str,
    payload: ContributionPayload,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    work = _work(db, auth.tenant_id, work_id, lock=True)
    from app.models import AssetVersion

    for asset_id in payload.input_asset_ids + (
        [payload.output_asset_id] if payload.output_asset_id else []
    ):
        asset = db.scalar(
            select(AssetVersion).where(
                AssetVersion.tenant_id == auth.tenant_id, AssetVersion.id == asset_id
            )
        )
        if asset is None or (asset_id == payload.output_asset_id and asset.work_id != work.id):
            raise HTTPException(status_code=404, detail="Contribution asset not found")
    previous = db.scalar(
        select(ContributionEvent)
        .where(ContributionEvent.tenant_id == auth.tenant_id, ContributionEvent.work_id == work.id)
        .order_by(ContributionEvent.sequence.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    row = ContributionEvent(
        tenant_id=auth.tenant_id,
        work_id=work.id,
        event_id=new_id("cev"),
        sequence=previous.sequence + 1 if previous else 1,
        actor_type=payload.actor_type,
        actor_id=payload.actor_id or auth.principal_id,
        event_type=payload.action_type,
        description=payload.description,
        classification=payload.classification,
        provider=payload.model_provider,
        model=payload.model_version,
        input_hash=payload.input_hash.lower() if payload.input_hash else None,
        output_hash=payload.output_hash.lower() if payload.output_hash else None,
        prompt_reference=payload.prompt_reference,
        source_reference=payload.source_reference,
        input_asset_ids=payload.input_asset_ids,
        output_asset_id=payload.output_asset_id,
        software_or_model=payload.software_or_model,
        human_decision=payload.human_decision,
        timestamp=utc(payload.timestamp) or now,
        evidence_artifact_reference=payload.evidence_artifact_reference,
        c2pa_reference=payload.c2pa_reference,
        previous_event_hash=previous.event_hash if previous else None,
        created_by=auth.principal_id or auth.credential_id or auth.actor_label,
        created_at=now,
    )
    row.event_hash = canonical_digest(_contribution_projection(row))
    db.add(row)
    try:
        db.flush()
        event = prepare_integrity_event(
            db,
            signer=container.signer,
            tenant_id=auth.tenant_id,
            event_type="CONTRIBUTION_EVENT_APPENDED",
            subject_type="work",
            subject_id=work.id,
            attributes={
                "event_id": row.event_id,
                "sequence": row.sequence,
                "event_hash": row.event_hash,
                "previous_event_hash": row.previous_event_hash,
            },
        )
        _audit(
            db,
            auth,
            tenant_id=auth.tenant_id,
            event_type="CONTRIBUTION_EVENT_APPENDED",
            resource_type="work",
            resource_id=work.id,
            attributes={"event_id": row.event_id, "event_hash": row.event_hash},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CONCURRENT_CONTRIBUTION_APPEND",
                "message": "Another contribution was appended concurrently. "
                "Retry against the new ledger head.",
            },
        ) from exc
    _publish(db, container, event)
    return _contribution_read(row)


def _events(db: Session, tenant_id: str, work_id: str):
    return db.scalars(
        select(ContributionEvent)
        .where(ContributionEvent.tenant_id == tenant_id, ContributionEvent.work_id == work_id)
        .order_by(ContributionEvent.sequence)
    ).all()


def _verify_chain(rows) -> dict[str, Any]:
    previous_hash = None
    for sequence, row in enumerate(rows, 1):
        if (
            row.sequence != sequence
            or row.previous_event_hash != previous_hash
            or row.event_hash != canonical_digest(_contribution_projection(row))
        ):
            return {
                "valid": False,
                "broken_sequence": row.sequence,
                "reason": "CONTRIBUTION_HASH_CHAIN_MISMATCH",
            }
        previous_hash = row.event_hash
    return {"valid": True, "event_count": len(rows), "head_hash": previous_hash}


@router.get("/works/{work_id}/contributions")
def list_contributions(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    _work(db, auth.tenant_id, work_id)
    rows = _events(db, auth.tenant_id, work_id)
    return {
        "work_id": work_id,
        "events": [_contribution_read(row) for row in rows],
        "verification": _verify_chain(rows),
        "copyrightability_determination": None,
    }


@router.get("/works/{work_id}/contributions/verify")
def verify_contributions(
    work_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_READ))],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    _work(db, auth.tenant_id, work_id)
    return {"work_id": work_id, **_verify_chain(_events(db, auth.tenant_id, work_id))}


VerificationScope = Literal["registration", "provenance", "rights", "evidence"]


class VerificationTokenPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expires_in_seconds: int = Field(default=86_400, ge=60, le=31_536_000)
    scopes: list[VerificationScope] = Field(
        default_factory=lambda: ["registration", "provenance", "rights", "evidence"],
        min_length=1,
        max_length=4,
    )


def _issue_token(
    resource_id: str,
    resource_type: str,
    payload: VerificationTokenPayload,
    auth: AuthContext,
    db: Session,
    *,
    public_base_url: str = "",
) -> dict[str, Any]:
    _work(db, auth.tenant_id, resource_id) if resource_type == "work" else _scan(
        db, auth.tenant_id, resource_id
    )
    raw_token = secrets.token_urlsafe(48)
    row = PublicVerificationToken(
        tenant_id=auth.tenant_id,
        resource_type=resource_type,
        resource_id=resource_id,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        scopes=sorted(set(payload.scopes)),
        expires_at=datetime.now(UTC) + timedelta(seconds=payload.expires_in_seconds),
    )
    db.add(row)
    db.flush()
    _audit(
        db,
        auth,
        tenant_id=auth.tenant_id,
        event_type="PUBLIC_VERIFICATION_TOKEN_ISSUED",
        resource_type=resource_type,
        resource_id=resource_id,
        attributes={"token_id": row.id, "scopes": row.scopes, "expires_at": iso(row.expires_at)},
    )
    db.commit()
    return {
        "token": raw_token,
        "token_id": row.id,
        "verification_path": f"/verify/{raw_token}",
        "verification_url": f"{public_base_url}/verify/{raw_token}" if public_base_url else None,
        "expires_at": row.expires_at,
        "public_asset_id": public_asset_id(resource_type, resource_id),
        "scopes": row.scopes,
    }


@router.post("/works/{work_id}/verification-token", status_code=status.HTTP_201_CREATED)
def issue_work_token(
    work_id: str,
    payload: VerificationTokenPayload,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.WORKS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return _issue_token(
        work_id,
        "work",
        payload,
        auth,
        db,
        public_base_url=container.settings.public_verification_base_url,
    )


@router.post("/scans/{scan_id}/verification-token", status_code=status.HTTP_201_CREATED)
def issue_scan_token(
    scan_id: str,
    payload: VerificationTokenPayload,
    response: Response,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict[str, Any]:
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return _issue_token(
        scan_id,
        "scan",
        payload,
        auth,
        db,
        public_base_url=container.settings.public_verification_base_url,
    )


@router.delete("/verification-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: str,
    auth: Annotated[
        AuthContext,
        Depends(
            require_any_scope(
                CredentialScope.WORKS_WRITE,
                CredentialScope.SCANS_WRITE,
                CredentialScope.RIGHTS_WRITE,
            )
        ),
    ],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    row = db.scalar(
        select(PublicVerificationToken).where(
            PublicVerificationToken.id == token_id,
            PublicVerificationToken.tenant_id == auth.tenant_id,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Verification token not found")
    resource_scope = (
        CredentialScope.WORKS_WRITE if row.resource_type == "work" else CredentialScope.SCANS_WRITE
    )
    if not (auth.has_scope(resource_scope) or auth.has_scope(CredentialScope.RIGHTS_WRITE)):
        raise HTTPException(
            status_code=403,
            detail={"code": "INSUFFICIENT_SCOPE", "required_scope": resource_scope.value},
        )
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        row.revoked_by = auth.principal_id
        _audit(
            db,
            auth,
            tenant_id=auth.tenant_id,
            event_type="PUBLIC_VERIFICATION_TOKEN_REVOKED",
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            attributes={"token_id": row.id},
        )
        db.commit()
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


def _public_tenant_db(request: Request, token: str):
    # Resolve only the opaque token in a short-lived bootstrap session. All
    # subsequent reads happen in a separate session with FORCE RLS applied.
    if len(token) != 64 or any(
        character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for character in token
    ):
        raise HTTPException(status_code=404, detail="Verification token not found or expired")
    container = request.app.state.container
    bootstrap = container.database.system_session()
    try:
        row = bootstrap.scalar(
            select(PublicVerificationToken).where(
                PublicVerificationToken.token_hash == hashlib.sha256(token.encode()).hexdigest()
            )
        )
        if row is None or (row.expires_at and utc(row.expires_at) <= datetime.now(UTC)):
            raise HTTPException(status_code=404, detail="Verification token not found or expired")
        if row.revoked_at:
            raise HTTPException(
                status_code=410, detail={"code": "VERIFICATION_REVOKED", "revoked": True}
            )
        tenant_id, token_id = row.tenant_id, row.id
    finally:
        bootstrap.close()
    db = container.database.session_factory()
    bind_tenant_context(db, tenant_id)
    request.state.public_verification_token_id = token_id
    try:
        yield db
    finally:
        db.close()


def _safe_sha256(value: Any) -> str | None:
    return (
        value.lower()
        if isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdefABCDEF" for character in value)
        else None
    )


def _public_rights_summary(
    db: Session,
    tenant_id: str,
    work_id: str,
    *,
    snapshot: dict | None = None,
) -> dict[str, Any] | None:
    work = db.scalar(
        select(Work.id).where(
            Work.id == work_id, Work.tenant_id == tenant_id, Work.deleted_at.is_(None)
        )
    )
    if work is None:
        return None
    if snapshot is not None:
        version = snapshot.get("version")
        digest = _safe_sha256(snapshot.get("digest_sha256"))
        if type(version) is not int or version < 1 or digest is None:
            return None
        row = _latest_policy(db, tenant_id, work_id, version)
        if row is None or row.digest_sha256 != digest:
            return None
    else:
        row = _latest_policy(db, tenant_id, work_id)
    state = policy_state(row)
    if snapshot is not None and state != "INTEGRITY_MISMATCH":
        recorded_state = snapshot.get("state")
        state = (
            recorded_state
            if isinstance(recorded_state, str)
            and recorded_state
            in {
                "ACTIVE",
                "UNKNOWN",
                "NOT_YET_EFFECTIVE",
                "EXPIRED",
                "REVOKED",
                "CONSENT_WITHDRAWN",
                "CONSENT_NOT_GRANTED",
                "INTEGRITY_MISMATCH",
            }
            else "UNKNOWN"
        )
    # Fixed shape, fixed enums. No arbitrary policy notes, contact, identity,
    # dimensions or free-form metadata can enter this public response.
    return {
        "policy_version": row.version if row else None,
        "policy_digest_sha256": _safe_sha256(row.digest_sha256) if row else None,
        "state": state,
        "temporal_binding": "AS_OF_SCAN" if snapshot is not None else "CURRENT_WORK_POLICY",
        "preferences": {
            key: (row.permissions or {}).get(key, "UNKNOWN")
            if row
            and (row.permissions or {}).get(key) in set(PermissionValue)
            and state != "INTEGRITY_MISMATCH"
            else "UNKNOWN"
            for key in PERMISSION_FIELDS
        },
        "creator_assertion": bool(row and not is_unknown_rights_baseline(row)),
        "unknown_registration_baseline": is_unknown_rights_baseline(row),
        "legal_conclusion": None,
    }


def _public_provenance(
    db: Session, *, tenant_id: str, resource_type: str, resource_id: str, packet: dict | None = None
) -> str:
    from app.models import ProvenanceRecord

    row = db.scalar(
        select(ProvenanceRecord)
        .where(
            ProvenanceRecord.tenant_id == tenant_id,
            ProvenanceRecord.subject_type == resource_type,
            ProvenanceRecord.subject_id == resource_id,
        )
        .order_by(ProvenanceRecord.created_at.desc())
        .limit(1)
    )
    normalized = {
        "VALID_TRUSTED": "VALID",
        "VALID_UNTRUSTED": "VALID_BUT_UNTRUSTED",
        "NOT_PRESENT": "ABSENT",
        "NOT_CHECKED": "UNSUPPORTED",
        "ERROR": "PARSE_ERROR",
    }
    packet_provenance = (packet or {}).get("provenance")
    value = (
        row.status
        if row
        else packet_provenance.get("status", "UNSUPPORTED")
        if isinstance(packet_provenance, dict)
        else "UNSUPPORTED"
    )
    value = normalized.get(str(value), str(value))
    return (
        value
        if value
        in {
            "VALID",
            "VALID_BUT_UNTRUSTED",
            "INVALID",
            "ABSENT",
            "UNSUPPORTED",
            "PROVIDER_UNAVAILABLE",
            "PARSE_ERROR",
        }
        else "UNSUPPORTED"
    )


@public_router.get("/{token}")
def public_verify(
    request: Request, response: Response, db: Annotated[Session, Depends(_public_tenant_db)]
) -> dict[str, Any]:
    response.headers.update(
        {
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        }
    )
    row = db.get(PublicVerificationToken, request.state.public_verification_token_id)
    # Recheck state in tenant scope to close revocation/expiry races.
    if (
        row is None
        or (row.expires_at and utc(row.expires_at) <= datetime.now(UTC))
        or row.resource_type not in {"work", "scan"}
    ):
        raise HTTPException(status_code=404, detail="Verification token not found or expired")
    if row.revoked_at:
        raise HTTPException(
            status_code=410, detail={"code": "VERIFICATION_REVOKED", "revoked": True}
        )
    target = (
        _work(db, row.tenant_id, row.resource_id)
        if row.resource_type == "work"
        else _scan(db, row.tenant_id, row.resource_id)
    )
    packet = (
        target.evidence_packet
        if row.resource_type == "scan" and isinstance(target.evidence_packet, dict)
        else {}
    )
    result: dict[str, Any] = {
        "schema": "creatorproof.public-verification.v1",
        "public_asset_id": public_asset_id(row.resource_type, row.resource_id),
        "resource_type": row.resource_type,
        "verification_timestamp": datetime.now(UTC),
        "revoked": False,
    }
    if "registration" in row.scopes:
        result["registration_status"] = (
            "REGISTERED"
            if row.resource_type == "work"
            else str(target.state)
            if str(target.state) in {"QUEUED", "PROCESSING", "COMPLETED", "FAILED"}
            else "UNKNOWN"
        )
    if "provenance" in row.scopes:
        result["provenance_status"] = _public_provenance(
            db,
            tenant_id=row.tenant_id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            packet=packet,
        )
    if "rights" in row.scopes:
        work_id = target.id if row.resource_type == "work" else target.top_match_work_id
        snapshot = None
        if row.resource_type == "scan":
            decision = packet.get("decision")
            inputs = decision.get("policy_inputs") if isinstance(decision, dict) else None
            facts = inputs.get("rights_facts") if isinstance(inputs, dict) else None
            snapshot = facts.get("rights_preferences") if isinstance(facts, dict) else None
            snapshot = snapshot if isinstance(snapshot, dict) else {}
        result["rights_policy_summary"] = (
            _public_rights_summary(db, row.tenant_id, work_id, snapshot=snapshot)
            if work_id
            else None
        )
    if "evidence" in row.scopes and row.resource_type == "scan":
        proof = packet.get("proof")
        result["packet_hash_sha256"] = _safe_sha256(
            proof.get("packet_hash_sha256") if isinstance(proof, dict) else None
        )
        result["public_evidence_version"] = (
            "creatorproof.evidence_packet.v1"
            if packet.get("schema") == "creatorproof.evidence_packet.v1"
            else None
        )
    row.last_used_at = datetime.now(UTC)
    _audit(
        db,
        None,
        tenant_id=row.tenant_id,
        event_type="PUBLIC_VERIFICATION_ACCESSED",
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        attributes={"token_id": row.id, "scopes": row.scopes},
    )
    db.commit()
    return result
