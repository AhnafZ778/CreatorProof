"""Durable scan execution.

Orchestration lives here rather than in ``app/services/evidence.py`` so the
evidence semantics owned by Agent A and the execution model owned by Agent B can
change independently. ``evidence.process_scan`` delegates to this module and
keeps its original signature for existing callers.

Guarantees implemented here:

* duplicate delivery is safe — a completed scan short-circuits;
* every expensive stage is leased, heartbeated and durably recorded;
* a stale worker cannot commit after its lease epoch has moved on;
* proof runs last, in its own stage, and can never rewrite a committed result;
* cancellation and deadlines are honoured at checkpoints between stages.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.domain.enums import MatchStatus, PolicyAction, ScanState
from app.domain.platform import (
    AuditEventType,
    DeletionReceiptState,
    RetryClass,
    ScanLifecycleState,
    StageName,
    StageState,
    StatementType,
)
from app.observability import METRICS, correlation_scope, log_event
from app.services.audit import record_audit_event
from app.services.canonical import canonical_digest
from app.services.metering import Meter, gpu_providers_in_use, record_usage
from app.services.orchestration import (
    ScanCancelled,
    StaleLeaseError,
    check_cancelled,
    derive_progress,
    set_lifecycle,
)
from app.services.runtime_telemetry import telemetry_scope
from app.services.tenancy import bind_tenant_context

logger = logging.getLogger("creatorproof.scan_runner")


def _progress_packet(
    stages: list[dict],
    started_at: str,
    *,
    substage: str,
    label: str,
    percent: int,
) -> dict:
    """Keep the Evidence Packet v1 progress shape the current UI already reads.

    ``progress.stage`` stays the fine-grained pipeline step so existing clients
    are unaffected. The durable ledger is exposed alongside it as ``stages`` so a
    truthful stage timeline can be rendered without guessing.
    """
    fallback = derive_progress(stages)
    return {
        "schema": "creatorproof.scan_progress.v1",
        "progress": {
            "stage": substage,
            "label": label,
            "percent": max(0, min(int(percent), 99)),
            "started_at": started_at,
            "updated_at": datetime.now(UTC).isoformat(),
            "poll_after_ms": 750,
            "can_resume": True,
            "durable_stage": (fallback or {}).get("stage", str(StageName.EVIDENCE)),
        },
        "stages": stages,
    }


def run_scan(container, scan_id: str) -> None:
    """Execute one scan through the durable stage ledger."""
    from app.models import Scan

    ledger = container.stage_ledger
    # A worker cannot bind a tenant until it resolves the globally unique scan
    # identifier. Use the explicit system session for that one lookup, then drop
    # privileges to the scan's tenant for every subsequent transaction.
    db = container.database.system_session()
    scan: Scan | None = None
    try:
        scan = db.get(Scan, scan_id)
        if scan is None:
            logger.warning("scan_not_found scan_id=%s", scan_id)
            return
        if scan.state == ScanState.FAILED:
            METRICS.increment("creatorproof_scan_duplicate_delivery_total")
            return

        bind_tenant_context(db, scan.tenant_id)
        with correlation_scope(scan.correlation_id):
            if scan.state == ScanState.COMPLETED:
                if not _resume_post_evidence_stages(container, db, scan, ledger):
                    # Duplicate delivery after all durable stages reached terminal
                    # success. The committed outcome wins.
                    METRICS.increment("creatorproof_scan_duplicate_delivery_total")
                return
            _run_stages(container, db, scan, ledger)
    except Exception:
        db.rollback()
        logger.exception("scan_runner_failed scan_id=%s", scan_id)
        raise
    finally:
        db.close()


def _run_stages(container, db, scan, ledger) -> None:
    from app.models import Scan

    ledger.ensure_stages(db, scan)
    started_at = datetime.now(UTC).isoformat()

    claimed = db.execute(
        update(Scan)
        .where(Scan.id == scan.id, Scan.state.in_([ScanState.QUEUED, ScanState.PROCESSING]))
        .values(state=ScanState.PROCESSING, error_code=None)
    )
    db.commit()
    if claimed.rowcount != 1:
        return
    db.refresh(scan)
    if scan.deadline_at is None:
        scan.deadline_at = datetime.now(UTC) + timedelta(
            seconds=container.settings.scan_deadline_seconds
        )
    set_lifecycle(db, scan, ScanLifecycleState.RUNNING)

    packet = _run_evidence_stage(container, db, scan, ledger, started_at)
    if packet is None:
        return

    statement = _run_statement_stage(container, db, scan, ledger, packet)
    if statement is None:
        # Proof and notification are causally downstream of the durable signed
        # statement. A redelivery will reconcile or retry this stage.
        _release_candidate_media(container, db, scan)
        return
    packet = _run_proof_stage(container, db, scan, ledger, packet, statement)
    _run_notify_stage(container, db, scan, ledger, packet, statement)
    _release_candidate_media(container, db, scan)


def _resume_post_evidence_stages(container, db, scan, ledger) -> bool:
    """Resume statement/proof/notify after evidence was durably committed.

    ``Scan.state=COMPLETED`` means the immutable evidence result exists; it must
    not prevent an interrupted strict-chain proof stage from being redelivered.
    """
    from app.models import EvidenceStatement, StageAttempt

    ledger.ensure_stages(db, scan)

    def stage_rows():
        return {
            str(row.stage): row
            for row in db.scalars(select(StageAttempt).where(StageAttempt.scan_id == scan.id)).all()
        }

    rows = stage_rows()
    stages = {stage: str(row.state) for stage, row in rows.items()}
    post_stages = (StageName.STATEMENT, StageName.PROOF, StageName.NOTIFY)
    claimable = {
        str(StageState.PENDING),
        str(StageState.READY),
        str(StageState.FAILED_RETRYABLE),
    }
    if not any(stages.get(str(stage)) in claimable for stage in post_stages):
        return False

    packet = scan.evidence_packet or {}
    statement_row = db.scalar(
        select(EvidenceStatement)
        .where(
            EvidenceStatement.tenant_id == scan.tenant_id,
            EvidenceStatement.scan_id == scan.id,
            EvidenceStatement.statement_type == str(StatementType.RESULT),
        )
        .order_by(EvidenceStatement.created_at.desc())
        .limit(1)
    )
    statement = None
    if statement_row is not None:
        statement = {
            "statement_id": statement_row.id,
            "payload_digest_sha256": statement_row.payload_digest_sha256,
        }
        statement_stage = rows.get(str(StageName.STATEMENT))
        if statement_stage is not None and str(statement_stage.state) != str(StageState.SUCCEEDED):
            # `issue_statement` commits before StageLedger.complete. Reconcile
            # that crash window to the immutable row instead of issuing a second
            # statement or letting proof overtake statement durability.
            db.execute(
                update(StageAttempt)
                .where(
                    StageAttempt.id == statement_stage.id,
                    StageAttempt.lease_epoch == statement_stage.lease_epoch,
                    StageAttempt.state == statement_stage.state,
                )
                .values(
                    state=StageState.SUCCEEDED,
                    output_digest=canonical_digest({"statement_id": statement_row.id}),
                    completed_at=datetime.now(UTC),
                    lease_owner=None,
                    lease_expires_at=None,
                    error_code=None,
                    retry_class=None,
                    progress_percent=100,
                )
            )
            db.commit()
    elif stages.get(str(StageName.STATEMENT)) in claimable:
        statement = _run_statement_stage(container, db, scan, ledger, packet)

    if statement is None:
        return True
    rows = stage_rows()
    if str(rows[str(StageName.STATEMENT)].state) != str(StageState.SUCCEEDED):
        return True

    if str(rows[str(StageName.PROOF)].state) in claimable:
        packet = _run_proof_stage(container, db, scan, ledger, packet, statement)
    rows = stage_rows()
    if str(rows[str(StageName.PROOF)].state) != str(StageState.SUCCEEDED):
        return True

    if str(rows[str(StageName.NOTIFY)].state) in claimable:
        _run_notify_stage(container, db, scan, ledger, packet, statement)
    _release_candidate_media(container, db, scan)
    return True


def _run_evidence_stage(container, db, scan, ledger, started_at: str):
    from app.services.evidence import build_evidence_packet

    epoch = ledger.acquire(
        db, scan_id=scan.id, stage=StageName.EVIDENCE, owner=container.worker_identity
    )
    if epoch is None:
        return None

    def report(substage: str, label: str, percent: int) -> None:
        ledger.record_progress(
            db,
            scan_id=scan.id,
            stage=StageName.EVIDENCE,
            epoch=epoch,
            percent=percent,
            label=label,
        )
        scan.evidence_packet = _progress_packet(
            ledger.snapshot(db, scan.id),
            started_at,
            substage=substage,
            label=label,
            percent=percent,
        )
        scan.reason_codes = ["SCAN_IN_PROGRESS"]
        db.commit()
        check_cancelled(db, scan.id)

    try:
        report("STARTING", "Starting the evidence checks", 2)
        if not scan.candidate_storage_key:
            raise ValueError("CANDIDATE_MISSING")
        raw = container.storage.read(scan.candidate_storage_key)
        evidence_started = time.perf_counter()
        created_at = scan.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        with telemetry_scope(
            {
                "model_bundle_id": container.model_bundle.bundle_id,
                "model_bundle_manifest_digest_sha256": (
                    container.model_bundle.manifest_digest_sha256
                ),
                "copy_query_policy": "SSCD_WHOLE_PLUS_FIVE_OVERLAPPING_REGIONS_V1",
            }
        ) as runtime_telemetry:
            runtime_telemetry.observe(
                "queue_age_ms",
                max(0.0, (datetime.now(UTC) - created_at).total_seconds() * 1000),
            )
            with METRICS.time_block(
                "creatorproof_stage_duration_ms", stage=str(StageName.EVIDENCE)
            ):
                packet = build_evidence_packet(
                    container,
                    db,
                    scan,
                    raw,
                    progress=report,
                    defer_proof=True,
                )
        evidence_seconds = time.perf_counter() - evidence_started
        gpu_providers = gpu_providers_in_use(container)
        if gpu_providers:
            record_usage(
                db,
                tenant_id=scan.tenant_id,
                meter=Meter.GPU_STAGE_SECONDS,
                quantity=max(1, round(evidence_seconds)),
                scan_id=scan.id,
                attributes={"stage": str(StageName.EVIDENCE), "providers": gpu_providers},
                commit=False,
            )
        ledger.complete(
            db,
            scan_id=scan.id,
            stage=StageName.EVIDENCE,
            epoch=epoch,
            output={"packet_hash": (packet.get("proof") or {}).get("packet_hash_sha256")},
        )
    except StaleLeaseError:
        logger.warning("evidence_stage_stale_lease scan_id=%s", scan.id)
        db.rollback()
        return None
    except BaseException as exc:  # noqa: BLE001 - classified below
        db.rollback()
        retry_class = ledger.fail(
            db, scan_id=scan.id, stage=StageName.EVIDENCE, epoch=epoch, exc=exc
        )
        _finalize_failure(db, scan, exc=exc, retry_class=retry_class)
        if retry_class == RetryClass.TRANSIENT:
            # Leave the scan claimable; the reaper or a redelivery picks it back up.
            raise
        return None

    scan.state = ScanState.COMPLETED
    scan.completed_at = datetime.now(UTC)
    set_lifecycle(db, scan, ScanLifecycleState.RESULT_READY, commit=False)
    db.commit()
    METRICS.increment(
        "creatorproof_scan_result_total",
        match_status=str(scan.match_status),
        policy_action=str(scan.policy_action),
    )
    log_event(
        logger,
        "scan_result_ready",
        scan_id=scan.id,
        match_status=scan.match_status,
        policy_action=scan.policy_action,
        coverage_status=(packet.get("scope") or {}).get("coverage_status"),
    )
    return packet


def _run_statement_stage(container, db, scan, ledger, packet: dict):
    from app.models import EvidenceStatement
    from app.services.statements import issue_statement

    epoch = ledger.acquire(
        db, scan_id=scan.id, stage=StageName.STATEMENT, owner=container.worker_identity
    )
    if epoch is None:
        return None
    try:
        existing = db.scalar(
            select(EvidenceStatement)
            .where(
                EvidenceStatement.tenant_id == scan.tenant_id,
                EvidenceStatement.scan_id == scan.id,
                EvidenceStatement.statement_type == str(StatementType.RESULT),
            )
            .order_by(EvidenceStatement.created_at.desc())
            .limit(1)
        )
        if existing is not None:
            statement = {
                "statement_id": existing.id,
                "payload_digest_sha256": existing.payload_digest_sha256,
            }
        else:
            statement = issue_statement(
                db,
                signer=container.signer,
                transparency=container.transparency,
                blockchain=getattr(container, "blockchain", None),
                scan=scan,
                packet=packet,
                statement_type=StatementType.RESULT,
                stage_digests=ledger.stage_digests(db, scan.id),
            )
        ledger.complete(
            db,
            scan_id=scan.id,
            stage=StageName.STATEMENT,
            epoch=epoch,
            output={"statement_id": statement["statement_id"]},
        )
        record_audit_event(
            db,
            tenant_id=scan.tenant_id,
            event_type=AuditEventType.STATEMENT_ISSUED,
            resource_type="scan",
            resource_id=scan.id,
            correlation_id=scan.correlation_id,
            attributes={"statement_id": statement["statement_id"]},
        )
        return statement
    except Exception as exc:
        db.rollback()
        ledger.fail(db, scan_id=scan.id, stage=StageName.STATEMENT, epoch=epoch, exc=exc)
        logger.exception("statement_stage_failed scan_id=%s", scan.id)
        return None


def _run_proof_stage(container, db, scan, ledger, packet: dict, statement) -> dict:
    """Anchor the packet commitment.

    This stage is deliberately isolated. A proof provider outage, a chain
    reorganisation or a missing signer changes only ``proof.anchor_status``; the
    evidence finding and the policy action are already committed.
    """
    epoch = ledger.acquire(
        db, scan_id=scan.id, stage=StageName.PROOF, owner=container.worker_identity
    )
    if epoch is None:
        return packet

    packet_hash = str((packet.get("proof") or {}).get("packet_hash_sha256") or "")
    try:
        with METRICS.time_block("creatorproof_stage_duration_ms", stage=str(StageName.PROOF)):
            blockchain = getattr(container, "blockchain", None)
            receipt = (
                blockchain.anchor_packet(
                    packet_hash=packet_hash,
                    scan_id=scan.id,
                    tenant_id=scan.tenant_id,
                )
                if blockchain is not None
                else container.proof_anchor.anchor(packet_hash)
            )
        proof_status, provider, proof_receipt = receipt.status, receipt.provider, receipt.receipt
    except Exception as exc:
        proof_status = "FAILED"
        provider = container.proof_anchor.name
        proof_receipt = {"error_code": f"PROOF_ANCHOR_FAILED:{type(exc).__name__}"}
        logger.warning("proof_anchor_raised scan_id=%s error=%s", scan.id, type(exc).__name__)

    updated = {
        **packet,
        "proof": {
            **(packet.get("proof") or {}),
            "anchor_status": str(proof_status),
            "provider": provider,
            "receipt": proof_receipt,
            "statement_id": (statement or {}).get("statement_id"),
            "statement_digest_sha256": (statement or {}).get("payload_digest_sha256"),
            "evidence_independent_of_proof": True,
        },
    }
    try:
        scan.anchor_status = str(proof_status)
        scan.evidence_packet = updated
        chain_satisfied = str(proof_status) == "ANCHORED"
        lifecycle = (
            ScanLifecycleState.COMPLETED
            if chain_satisfied or not container.settings.proof_require_chain
            else ScanLifecycleState.RESULT_READY
        )
        set_lifecycle(db, scan, lifecycle, commit=False)
        db.commit()
        if container.settings.proof_require_chain and not chain_satisfied:
            # Preserve the evidence result while leaving PROOF claimable for a
            # redelivery/startup recovery. Chain finality is an operational state,
            # never an excuse to discard or rewrite the computed evidence.
            retry_class = ledger.fail(
                db,
                scan_id=scan.id,
                stage=StageName.PROOF,
                epoch=epoch,
                exc=ConnectionError(f"PUBLIC_CHAIN_ANCHOR_{proof_status}"),
            )
            if retry_class != RetryClass.TRANSIENT:
                logger.error("strict_chain_proof_retry_budget_exhausted scan_id=%s", scan.id)
        else:
            ledger.complete(
                db,
                scan_id=scan.id,
                stage=StageName.PROOF,
                epoch=epoch,
                output={"anchor_status": str(proof_status)},
            )
        METRICS.increment("creatorproof_proof_total", anchor_status=str(proof_status))
        if str(proof_status) == "ANCHORED":
            record_audit_event(
                db,
                tenant_id=scan.tenant_id,
                event_type=AuditEventType.PROOF_ANCHORED,
                resource_type="scan",
                resource_id=scan.id,
                correlation_id=scan.correlation_id,
                attributes={"provider": provider},
            )
            record_usage(
                db,
                tenant_id=scan.tenant_id,
                meter=Meter.PROOF_ANCHOR,
                scan_id=scan.id,
                attributes={"provider": provider},
            )
    except Exception:
        db.rollback()
        logger.exception("proof_stage_persist_failed scan_id=%s", scan.id)
        return packet
    return updated


def _run_notify_stage(container, db, scan, ledger, packet: dict, statement) -> None:
    from app.services.review import open_review_case_if_needed
    from app.services.webhooks import queue_scan_completed

    if container.settings.proof_require_chain and str(scan.lifecycle_state) != str(
        ScanLifecycleState.COMPLETED
    ):
        # In strict mode "completed" notifications are truthful only after the
        # public-chain receipt satisfies the configured confirmation policy.
        return
    epoch = ledger.acquire(
        db, scan_id=scan.id, stage=StageName.NOTIFY, owner=container.worker_identity
    )
    if epoch is None:
        return
    try:
        case = open_review_case_if_needed(
            db,
            scan,
            statement_id=(statement or {}).get("statement_id"),
            signer=container.signer,
            transparency=container.transparency,
            blockchain=getattr(container, "blockchain", None),
        )
        queue_scan_completed(
            db,
            scan=scan,
            packet=packet,
            statement=statement,
            review_case_id=case.id if case is not None else None,
        )
        ledger.complete(
            db,
            scan_id=scan.id,
            stage=StageName.NOTIFY,
            epoch=epoch,
            output={"review_case_id": case.id if case is not None else None},
        )
    except Exception as exc:
        db.rollback()
        ledger.fail(db, scan_id=scan.id, stage=StageName.NOTIFY, epoch=epoch, exc=exc)
        logger.exception("notify_stage_failed scan_id=%s", scan.id)


def _finalize_failure(db, scan, *, exc: BaseException, retry_class: RetryClass) -> None:
    from app.models import Scan

    if retry_class == RetryClass.TRANSIENT:
        db.execute(
            update(Scan)
            .where(Scan.id == scan.id)
            .values(state=ScanState.QUEUED, error_code=type(exc).__name__)
        )
        db.commit()
        return

    cancelled = isinstance(exc, ScanCancelled)
    db.execute(
        update(Scan)
        .where(Scan.id == scan.id)
        .values(
            state=ScanState.FAILED,
            lifecycle_state=str(
                ScanLifecycleState.CANCELLED if cancelled else ScanLifecycleState.FAILED
            ),
            match_status=str(MatchStatus.ERROR),
            policy_action=str(PolicyAction.REVIEW),
            error_code=str(exc) if cancelled else type(exc).__name__,
            reason_codes=["SCAN_CANCELLED"] if cancelled else ["PIPELINE_ERROR"],
            completed_at=datetime.now(UTC),
        )
    )
    db.commit()
    METRICS.increment(
        "creatorproof_scan_failed_total",
        retry_class=str(retry_class),
    )


def _release_candidate_media(container, db, scan) -> None:
    """Delete short-lived candidate media and record a deletion receipt.

    Derived artifacts share the candidate prefix, so the whole prefix is removed
    rather than only the original upload.
    """
    from app.models import DeletionReceipt

    if container.settings.candidate_retention_seconds != 0:
        return
    if not scan.candidate_storage_key:
        return
    prefix = f"scans/{scan.tenant_id}/{scan.id}/"
    try:
        deleted = container.storage.delete_prefix(prefix)
    except Exception as exc:
        logger.warning("candidate_delete_failed scan_id=%s error=%s", scan.id, type(exc).__name__)
        db.add(
            DeletionReceipt(
                tenant_id=scan.tenant_id,
                requested_scope={"scan_id": scan.id, "prefix": prefix},
                state=DeletionReceiptState.FAILED,
                objects_retained=[{"prefix": prefix, "reason": type(exc).__name__}],
            )
        )
        db.commit()
        return
    db.add(
        DeletionReceipt(
            tenant_id=scan.tenant_id,
            requested_scope={"scan_id": scan.id, "prefix": prefix},
            state=DeletionReceiptState.COMPLETED,
            objects_deleted=deleted,
            verified_at=datetime.now(UTC),
        )
    )
    db.commit()


def recover_orphaned_scans(container) -> int:
    """Re-publish accepted work that no longer has a live stage attempt.

    Runs at startup so an API or worker crash cannot strand a scan permanently.
    """
    from app.models import Scan
    from app.services.orchestration import TOPIC_SCAN_ACCEPTED, enqueue_outbox

    db = container.database.system_session()
    recovered = 0
    try:
        stranded = (
            db.query(Scan)
            .filter(
                (Scan.state.in_([ScanState.QUEUED, ScanState.PROCESSING]))
                | (
                    (Scan.state == ScanState.COMPLETED)
                    & (Scan.lifecycle_state == str(ScanLifecycleState.RESULT_READY))
                )
            )
            .limit(200)
            .all()
        )
        for scan in stranded:
            enqueue_outbox(
                db,
                tenant_id=scan.tenant_id,
                topic=TOPIC_SCAN_ACCEPTED,
                payload={"scan_id": scan.id, "recovery": True},
            )
            recovered += 1
        if recovered:
            db.commit()
            log_event(logger, "orphaned_scans_requeued", count=recovered)
    except Exception:
        db.rollback()
        logger.exception("orphan_recovery_failed")
    finally:
        db.close()
    return recovered


def stage_states(container, scan_id: str) -> list[dict]:
    db = container.database.session_factory()
    try:
        return container.stage_ledger.snapshot(db, scan_id)
    finally:
        db.close()
