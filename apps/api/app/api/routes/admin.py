"""Operator-only monitoring and reviewable notice drafting."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import CredentialScope
from app.models import (
    AuditEvent,
    InvestigationOutput,
    InvestigationRun,
    MarketplaceAsset,
    ReviewCase,
    Scan,
    ScanInputBinding,
    TakedownDraft,
    Work,
)
from app.schemas import (
    MarketplaceAssetRead,
    MarketplaceMonitorRead,
    MarketplaceMonitorRequest,
    TakedownDraftRead,
    TakedownDraftRequest,
    TakedownSendRequest,
    UserDetectionRead,
)
from app.services.admin_review import (
    POSITIVE_ORIGIN_CLASSIFICATIONS,
    copyright_draft_block_reason,
    review_signal,
)
from app.services.aiand import AiAndClient, AiAndError, evidence_packet_commitment
from app.services.marketplaces import MarketplaceError
from app.services.takedowns import (
    TEMPLATES,
    build_notice,
    classify_scan,
    infer_country,
    normalize_jurisdiction,
)

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _provider_error(exc: MarketplaceError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": str(exc)})


def _asset_read(asset: MarketplaceAsset) -> MarketplaceAssetRead:
    return MarketplaceAssetRead(
        id=asset.id,
        provider=asset.provider,
        external_id=asset.external_id,
        title=asset.title,
        source_url=asset.source_url,
        image_url=asset.image_url,
        thumbnail_url=asset.thumbnail_url,
        creator=asset.creator,
        width=asset.width,
        height=asset.height,
        metadata=asset.provider_metadata or {},
        observation_id=asset.observation_id,
        scan_id=asset.scan_id,
        classification=asset.classification,
        country_code=asset.country_code,
        jurisdiction_basis=asset.jurisdiction_basis,
        first_seen_at=asset.first_seen_at,
        last_seen_at=asset.last_seen_at,
    )


def _refresh_classification(db: Session, assets: list[MarketplaceAsset]) -> None:
    changed = False
    for asset in assets:
        if not asset.scan_id:
            continue
        scan = db.get(Scan, asset.scan_id)
        if scan is None or scan.state not in {"COMPLETED", "FAILED"}:
            continue
        classification = classify_scan(scan)
        if asset.classification != classification:
            asset.classification = classification
            changed = True
    if changed:
        db.commit()


@router.post("/marketplaces/monitor", response_model=MarketplaceMonitorRead)
async def monitor_marketplace(
    payload: MarketplaceMonitorRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.SCANS_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> MarketplaceMonitorRead:
    """Fetch once, persist every observation, and scan only unseen provider IDs."""
    per_page = min(payload.per_page, container.settings.marketplace_max_results)
    try:
        candidates = await container.marketplaces.search(
            payload.provider, query=payload.query, page=payload.page, per_page=per_page
        )
    except MarketplaceError as exc:
        raise _provider_error(exc) from exc
    new_assets: list[MarketplaceAsset] = []
    duplicates = 0
    for candidate in candidates:
        observation = container.marketplaces.observe(
            auth.tenant_id,
            candidate,
            search={"query": payload.query.strip(), "page": payload.page, "monitor": True},
        )
        asset = db.scalar(
            select(MarketplaceAsset).where(
                MarketplaceAsset.tenant_id == auth.tenant_id,
                MarketplaceAsset.provider == candidate.provider,
                MarketplaceAsset.external_id == candidate.external_id,
            )
        )
        now = datetime.now(UTC)
        if asset is not None:
            asset.last_seen_at = now
            asset.observation_id = observation["observation_id"]
            duplicates += 1
            continue
        country_code, basis = (
            (None, "ebay_item_location_is_not_seller_residence")
            if candidate.provider == "ebay"
            else infer_country(candidate.metadata, candidate.source_url)
        )
        asset = MarketplaceAsset(
            tenant_id=auth.tenant_id,
            provider=candidate.provider,
            external_id=candidate.external_id,
            title=candidate.title,
            source_url=candidate.source_url,
            image_url=candidate.image_url,
            thumbnail_url=candidate.thumbnail_url,
            creator=candidate.creator,
            width=candidate.width,
            height=candidate.height,
            provider_metadata=candidate.metadata,
            observation_id=observation["observation_id"],
            classification="UNCLASSIFIED",
            country_code=country_code,
            jurisdiction_basis=basis,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(asset)
        db.flush()
        # Commit the durable discovery record before downloading/scanning. A
        # provider failure must not roll back the history row or poison the
        # transaction used by the normal scan intake path.
        db.commit()
        if payload.scan_new:
            try:
                raw = await container.marketplaces.download(observation)
                from app.api.routes.scans import _create_scan_bytes

                scan = _create_scan_bytes(
                    raw=raw,
                    catalog_id=payload.catalog_id,
                    intended_use=payload.intended_use,
                    idempotency_key=f"admin-monitor:{asset.id}:{payload.catalog_id}"[:160],
                    auth=auth,
                    db=db,
                    container=container,
                    source_observation=observation,
                )
                asset.scan_id = scan.id
            except MarketplaceError:
                # Keep the durable asset even if one provider download fails.
                db.rollback()
                asset = db.get(MarketplaceAsset, asset.id)
                if asset is not None:
                    asset.classification = "DOWNLOAD_FAILED"
            except Exception:
                db.rollback()
                asset = db.get(MarketplaceAsset, asset.id)
                if asset is not None:
                    asset.classification = "SCAN_FAILED"
        new_assets.append(asset)
    db.commit()
    history = list(
        db.scalars(
            select(MarketplaceAsset)
            .where(MarketplaceAsset.tenant_id == auth.tenant_id)
            .order_by(MarketplaceAsset.last_seen_at.desc())
            .limit(200)
        ).all()
    )
    _refresh_classification(db, history)
    return MarketplaceMonitorRead(
        provider=payload.provider,
        query=payload.query.strip(),
        checked_at=datetime.now(UTC),
        new_images=[_asset_read(asset) for asset in new_assets],
        history=[_asset_read(asset) for asset in history],
        duplicate_count=duplicates,
    )


@router.get("/marketplaces/monitor", response_model=list[MarketplaceAssetRead])
def list_monitored_assets(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_READ))],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[MarketplaceAssetRead]:
    assets = list(
        db.scalars(
            select(MarketplaceAsset)
            .where(MarketplaceAsset.tenant_id == auth.tenant_id)
            .order_by(MarketplaceAsset.last_seen_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    _refresh_classification(db, assets)
    return [_asset_read(asset) for asset in assets]


def _country_for_scan(db: Session, scan: Scan) -> str | None:
    binding = db.scalar(
        select(ScanInputBinding).where(
            ScanInputBinding.scan_id == scan.id,
            ScanInputBinding.tenant_id == scan.tenant_id,
        )
    )
    value = (
        (binding.requested_capabilities or {}).get("submission_country_code") if binding else None
    )
    return str(value).upper() if value else None


def _flagged_scan_filter():
    """SQL counterpart to review_signal; filtering precedes pagination."""
    return or_(
        Scan.policy_action.in_(["REVIEW", "BLOCK"]),
        Scan.match_status.in_(["MATCH_FOUND", "INCONCLUSIVE"]),
        Scan.evidence_packet["synthetic_origin"]["classification"]
        .as_string()
        .in_(POSITIVE_ORIGIN_CLASSIFICATIONS),
        and_(
            Scan.evidence_packet["style_analysis"]["learned_provider_active"]
            .as_boolean()
            .is_(True),
            Scan.evidence_packet["style_analysis"]["decision"]["review_recommended"]
            .as_boolean()
            .is_(True),
        ),
    )


def _tenant_work(db: Session, scan: Scan, work_id: str | None) -> Work | None:
    if not work_id:
        return None
    return db.scalar(select(Work).where(Work.id == work_id, Work.tenant_id == scan.tenant_id))


def _work_details(work: Work | None) -> dict | None:
    if work is None:
        return None
    return {
        "id": work.id,
        "title": work.title,
        "claimant": work.claimant,
        "catalog_id": work.catalog_id,
        "claim_state": work.claim_state,
        "rights_path": work.rights_path,
        "allowed_uses": work.allowed_uses or [],
        "deleted": work.deleted_at is not None,
    }


def _detection_read(db: Session, container: Container, scan: Scan) -> UserDetectionRead:
    from app.services.retention import candidate_expired

    signal = review_signal(scan)
    packet = scan.evidence_packet or {}
    context = scan.submission_context
    binding = db.scalar(
        select(ScanInputBinding).where(
            ScanInputBinding.scan_id == scan.id, ScanInputBinding.tenant_id == scan.tenant_id
        )
    )
    observation = (
        ((binding.requested_capabilities or {}).get("marketplace_observation") if binding else None)
        or packet.get("source_observation")
        or {}
    )
    matched_work = (
        _tenant_work(db, scan, scan.top_match_work_id)
        if scan.match_status == "MATCH_FOUND"
        else None
    )
    reference_work = matched_work
    if reference_work is None:
        # A comparison reference is a nomination, not a copy finding.
        profiles = (packet.get("style_analysis") or {}).get("top_profiles") or []
        matches = packet.get("matches") or []
        reference_id = (profiles[0].get("exemplar_work_id") if profiles else None) or (
            matches[0].get("work_id") if matches else None
        )
        reference_work = _tenant_work(db, scan, reference_id)
    case = db.scalar(
        select(ReviewCase).where(
            ReviewCase.scan_id == scan.id, ReviewCase.tenant_id == scan.tenant_id
        )
    )
    retention = container.settings.candidate_retention_seconds
    completed_at = scan.completed_at or scan.created_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    expires = completed_at + timedelta(seconds=max(0, retention))
    expired = candidate_expired(scan, retention)
    media_status = (
        "expired" if expired else "available" if scan.candidate_storage_key else "not_retained"
    )
    block_reason = copyright_draft_block_reason(scan, matched_work, case)
    summary = (
        "The assessment needs additional evidence or working checks. No misuse finding was made."
        if signal["category"] == "ASSESSMENT_GAP"
        else (
            "Compare the retained evidence and confirm rights, permission, "
            "and context before action."
        )
    )
    if matched_work and scan.policy_action == "PASS_BY_POLICY":
        summary = (
            "A registered work matched; the recorded policy permits this use. "
            "Verify permission before action."
        )
    return UserDetectionRead(
        scan_id=scan.id,
        country_code=context.get("country_code"),
        jurisdiction=normalize_jurisdiction(context.get("country_code")),
        country_basis=context["country_basis"],
        match_status=scan.match_status,
        policy_action=scan.policy_action,
        classification=classify_scan(scan),
        candidate_sha256=scan.candidate_sha256,
        matched_work_id=matched_work.id if matched_work else None,
        matched_work=_work_details(matched_work),
        reference_work=_work_details(reference_work),
        evidence_packet=packet,
        catalog_id=scan.catalog_id,
        intended_use=scan.intended_use,
        use_context=context["use_context"],
        submission_context=context,
        source_url=context.get("source_url"),
        source_provider=observation.get("provider"),
        source_metadata={
            "basis": context["source_basis"],
            **(
                {
                    "observation_id": observation.get("observation_id"),
                    "external_id": observation.get("external_id"),
                    "title": observation.get("title"),
                    "creator": observation.get("creator"),
                    "observed_at": observation.get("observed_at"),
                    "metadata": observation.get("metadata") or {},
                }
                if observation
                else {}
            ),
        },
        category=signal["category"],
        flag_reasons=signal["reasons"],
        reason_codes=scan.reason_codes or [],
        review_summary=summary,
        candidate_media_url=f"/v1/scans/{scan.id}/media" if media_status == "available" else None,
        candidate_media_status=media_status,
        candidate_media_expires_at=expires,
        reference_media_url=(
            f"/v1/works/{reference_work.id}/media"
            if reference_work and reference_work.deleted_at is None
            else None
        ),
        review_case={
            "id": case.id,
            "state": case.state,
            "disposition": case.disposition,
            "priority": case.priority,
        }
        if case
        else None,
        takedown_eligible=block_reason is None,
        takedown_block_reason=block_reason,
        created_at=scan.created_at,
        completed_at=scan.completed_at,
    )


@router.get("/user-detections", response_model=list[UserDetectionRead])
def list_user_detections(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_READ))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    scan_id: Annotated[str | None, Query(max_length=64)] = None,
) -> list[UserDetectionRead]:
    """Tenant-scoped durable review inbox, including non-copy flags and assessment gaps."""
    query = select(Scan).where(
        Scan.tenant_id == auth.tenant_id,
        Scan.state == "COMPLETED",
        _flagged_scan_filter(),
    )
    if scan_id:
        query = query.where(Scan.id == scan_id)
    scans = list(
        db.scalars(
            query.order_by(Scan.completed_at.desc(), Scan.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return [_detection_read(db, container, scan) for scan in scans]


@router.post("/user-detections/{scan_id}/review-case")
def ensure_detection_review_case(
    scan_id: str,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Open the accountable human workflow for historical flags, once per scan."""
    from app.services.review import open_review_case_if_needed

    scan = db.scalar(select(Scan).where(Scan.id == scan_id, Scan.tenant_id == auth.tenant_id))
    if scan is None:
        raise HTTPException(404, detail="User detection scan not found")
    if review_signal(scan)["status"] != "needs_review":
        raise HTTPException(409, detail="A completed flagged scan is required for review")
    try:
        case = open_review_case_if_needed(
            db,
            scan,
            signer=container.signer,
            transparency=container.transparency,
            blockchain=container.blockchain,
        )
    except IntegrityError:
        # A concurrent opener can win the unique tenant+scan identity.
        db.rollback()
        case = db.scalar(
            select(ReviewCase).where(
                ReviewCase.scan_id == scan_id, ReviewCase.tenant_id == auth.tenant_id
            )
        )
        if case is None:
            raise
    return {
        "id": case.id,
        "state": case.state,
        "disposition": case.disposition,
        "priority": case.priority,
    }


async def _generate_notice(
    *,
    container: Container,
    db: Session,
    auth: AuthContext,
    scan: Scan | None,
    jurisdiction: str,
    subject: str,
    body: str,
    evidence: dict,
) -> tuple[str, str, str, str | None, str | None]:
    template = TEMPLATES.get(jurisdiction, TEMPLATES["GENERIC"])
    # A remote AI result must bind to a completed stored evidence packet. An
    # unscanned marketplace discovery still gets the deterministic review draft.
    if scan is None or scan.state != "COMPLETED" or not scan.evidence_packet:
        return subject, body, "template_fallback", None, None
    try:
        packet_hash = evidence_packet_commitment(scan.evidence_packet)
    except AiAndError:
        return subject, body, "template_fallback", None, None
    run = InvestigationRun(
        tenant_id=auth.tenant_id,
        scan_id=scan.id,
        status="RUNNING",
        requested_by=auth.principal_id or auth.actor_label,
        provider="aiand",
        model=container.settings.aiand_model,
        prompt_template_version="creatorproof.notice-layout.v1",
        evidence_packet_hash=packet_hash,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    try:
        generated = await AiAndClient(container.settings).draft_notice_result(
            subject_hint=subject,
            deterministic_notice=body,
            jurisdiction_label=template.label,
            evidence=evidence,
        )
        run.status = "COMPLETED"
        run.input_hash = generated.input_hash
        run.completed_at = datetime.now(UTC)
        payload = generated.payload
        output = InvestigationOutput(
            tenant_id=auth.tenant_id,
            run_id=run.id,
            provider=generated.provider,
            model=generated.model,
            summary=payload["summary"],
            evidence_references=payload["evidence_references"],
            missing_facts=payload["missing_facts"],
            next_steps=payload["next_steps"],
            duplicate_groups=payload["duplicate_groups"],
            factual_notice_draft=payload["factual_notice_draft"],
            unsupported_claims=payload["unsupported_claims"],
            output_hash=generated.output_hash,
        )
        db.add(output)
        db.flush()
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
                    "packet_hash": run.evidence_packet_hash,
                    "output_hash": generated.output_hash,
                    "purpose": "NOTICE_DRAFT",
                },
            )
        )
        db.commit()
        notice = payload["factual_notice_draft"]
        return notice["subject"], notice["body"], "aiand", generated.model, output.id
    except AiAndError:
        run.status = "FAILED"
        run.error_code = "AIAND_UNAVAILABLE"
        run.completed_at = datetime.now(UTC)
        db.commit()
        return subject, body, "template_fallback", None, None


@router.get("/takedowns/drafts", response_model=list[TakedownDraftRead])
def list_takedown_drafts(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_READ))],
    db: Annotated[Session, Depends(get_db)],
    scan_id: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[TakedownDraft]:
    """Read durable drafts without regenerating them or calling an inference provider."""
    query = select(TakedownDraft).where(TakedownDraft.tenant_id == auth.tenant_id)
    if scan_id:
        # Marketplace drafts retain the asset link; its recorded scan is also searchable.
        asset_ids = select(MarketplaceAsset.id).where(
            MarketplaceAsset.tenant_id == auth.tenant_id,
            MarketplaceAsset.scan_id == scan_id,
        )
        query = query.where(
            or_(TakedownDraft.scan_id == scan_id, TakedownDraft.marketplace_asset_id.in_(asset_ids))
        )
    return list(db.scalars(query.order_by(TakedownDraft.created_at.desc()).limit(limit)).all())


@router.post(
    "/takedowns/drafts", response_model=TakedownDraftRead, status_code=status.HTTP_201_CREATED
)
async def create_takedown_draft(
    payload: TakedownDraftRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> TakedownDraft:
    if not payload.marketplace_asset_id and not payload.scan_id:
        raise HTTPException(422, detail="marketplace_asset_id or scan_id is required")
    if payload.marketplace_asset_id and payload.scan_id:
        raise HTTPException(422, detail="Choose one detection source")
    asset = db.scalar(
        select(MarketplaceAsset).where(
            MarketplaceAsset.id == payload.marketplace_asset_id,
            MarketplaceAsset.tenant_id == auth.tenant_id,
        )
    )
    if payload.marketplace_asset_id and asset is None:
        raise HTTPException(404, detail="Monitored marketplace asset not found")
    scan = None
    if payload.scan_id:
        scan = db.scalar(
            select(Scan).where(Scan.id == payload.scan_id, Scan.tenant_id == auth.tenant_id)
        )
        if scan is None:
            raise HTTPException(404, detail="User detection scan not found")
        if scan.state != "COMPLETED" or scan.match_status != "MATCH_FOUND":
            raise HTTPException(409, detail="A takedown draft requires a completed catalog match")
    notice_scan = scan
    if asset and asset.scan_id:
        notice_scan = db.scalar(
            select(Scan).where(
                Scan.id == asset.scan_id,
                Scan.tenant_id == auth.tenant_id,
            )
        )
    matched_work = (
        _tenant_work(db, notice_scan, notice_scan.top_match_work_id) if notice_scan else None
    )
    review_case = (
        db.scalar(
            select(ReviewCase).where(
                ReviewCase.scan_id == notice_scan.id, ReviewCase.tenant_id == auth.tenant_id
            )
        )
        if notice_scan
        else None
    )
    block_reason = copyright_draft_block_reason(notice_scan, matched_work, review_case)
    if block_reason:
        raise HTTPException(
            409, detail={"code": "COPYRIGHT_NOTICE_NOT_SUPPORTED", "message": block_reason}
        )
    jurisdiction = normalize_jurisdiction(payload.jurisdiction)
    submission = notice_scan.submission_context
    source_url = str(
        payload.infringing_url
        or (
            asset.source_url
            if asset
            else submission.get("source_url")
            or "[OPERATOR: add the exact public URL of the submitted copy]"
        )
    )
    creator_name = asset.creator if asset else None
    evidence = {
        "scan_id": notice_scan.id,
        "marketplace_asset_id": asset.id if asset else None,
        "match_status": notice_scan.match_status,
        "matched_work_id": matched_work.id,
        "matched_work": _work_details(matched_work),
        "policy_action": notice_scan.policy_action,
        "reason_codes": notice_scan.reason_codes or [],
        "submission_context": submission,
        "source_url": source_url,
        "evidence_summary": payload.evidence_summary,
    }
    subject, body = build_notice(
        jurisdiction=jurisdiction,
        claimant_name=payload.claimant_name,
        claimant_email=payload.claimant_email,
        protected_title=matched_work.title,
        protected_url=str(payload.protected_url),
        infringing_url=source_url,
        evidence_summary=payload.evidence_summary,
        creator_name=creator_name,
    )
    (
        subject,
        body,
        generation_provider,
        generation_model,
        investigation_output_id,
    ) = await _generate_notice(
        container=container,
        db=db,
        auth=auth,
        scan=notice_scan,
        jurisdiction=jurisdiction,
        subject=subject,
        body=body,
        evidence=evidence,
    )
    draft = TakedownDraft(
        tenant_id=auth.tenant_id,
        marketplace_asset_id=asset.id if asset else None,
        scan_id=scan.id if scan else None,
        jurisdiction=jurisdiction,
        recipient_email=payload.recipient_email,
        # Submission locale determines a suggested template, not another person's residence.
        recipient_country_code=asset.country_code if asset else None,
        subject=subject,
        body=body,
        generation_provider=generation_provider,
        generation_model=generation_model,
        investigation_output_id=investigation_output_id,
        state="DRAFT",
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.post("/takedowns/{draft_id}/send", response_model=TakedownDraftRead)
def mark_takedown_sent(
    draft_id: str,
    payload: TakedownSendRequest,
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.REVIEW_WRITE))],
    db: Annotated[Session, Depends(get_db)],
) -> TakedownDraft:
    draft = db.scalar(
        select(TakedownDraft).where(
            TakedownDraft.id == draft_id, TakedownDraft.tenant_id == auth.tenant_id
        )
    )
    if draft is None:
        raise HTTPException(404, detail="Takedown draft not found")
    if draft.state == "SENT":
        return draft
    if payload.recipient_email:
        draft.recipient_email = payload.recipient_email
    if payload.delivery == "mailto" and not draft.recipient_email:
        raise HTTPException(422, detail="A recipient email is required for mailto delivery")
    # Delivery is deliberately explicit. The API records the operator's action;
    # the browser opens mailto or the operator uses the host's official notice form.
    draft.state = "MAILTO_OPENED" if payload.delivery == "mailto" else "READY_FOR_MANUAL_SUBMISSION"
    draft.sent_at = datetime.now(UTC)
    db.commit()
    db.refresh(draft)
    return draft
