"""Purposeful, durable public-chain anchoring.

Uploaded works and evidence stay off-chain. CreatorProof commits only 32-byte
hashes: an evidence-packet commitment is submitted directly, while registrations
and lifecycle changes share signed transparency checkpoints for cost-efficient
batch anchoring.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.enums import AnchorStatus
from app.domain.platform import BlockchainAnchorJobState, BlockchainCommitmentType
from app.observability import METRICS
from app.providers.contracts import ProofReceipt

logger = logging.getLogger("creatorproof.blockchain")

INTEGRITY_EVENT_SCHEMA = "creatorproof.integrity_event.v1"
ACTIVE_JOB_STATES = (
    BlockchainAnchorJobState.PENDING,
    BlockchainAnchorJobState.PREPARED,
    BlockchainAnchorJobState.SUBMITTED,
    BlockchainAnchorJobState.RETRYABLE,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


def _normalized_hash(value: str) -> str:
    normalized = value.removeprefix("0x").lower()
    if len(normalized) != 64:
        raise ValueError("Blockchain commitments must be 32-byte hexadecimal digests")
    bytes.fromhex(normalized)
    return normalized


def deployment_id(settings) -> str:
    """Stable, non-secret identifier for the independently pinned deployment."""
    descriptor = deployment_manifest(settings)
    encoded = json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def deployment_manifest(settings) -> dict:
    """Canonical public descriptor hashed by API, browser and offline clients."""
    return {
        "schema": "creatorproof.blockchain_deployment.v1",
        "chain_id": settings.eas_chain_id,
        "contract_address": settings.eas_contract_address.lower(),
        "schema_uid": settings.eas_schema_uid.lower(),
        "checkpoint_schema_uid": settings.eas_checkpoint_schema_uid.lower(),
        "schema_definition": settings.eas_schema_definition,
        "checkpoint_schema_definition": settings.eas_checkpoint_schema_definition,
        "recipient": settings.eas_recipient.lower(),
        "required_attester_address": settings.eas_required_attester_address.lower(),
        "expected_contract_code_sha256": settings.eas_expected_contract_code_sha256.lower(),
        "finality_policy": settings.eas_finality_policy,
    }


def signer_lease_id(provider, settings) -> str:
    """Mutex identity for one EVM account, independent of schemas/policies."""
    provider_status: dict = {}
    actual_address = getattr(provider, "attester_address", "")
    actual_chain_id = getattr(provider, "chain_id", None)
    if not actual_address or actual_chain_id is None:
        try:
            provider_status = provider.status()
        except Exception:
            provider_status = {}
    address = str(
        actual_address
        or provider_status.get("attester_address")
        or getattr(provider, "required_attester_address", "")
        or settings.eas_required_attester_address
        or ""
    ).lower()
    chain_id = actual_chain_id
    if chain_id is None:
        chain_id = provider_status.get("live_chain_id") or provider_status.get("chain_id")
    if chain_id is None:
        chain_id = settings.eas_chain_id
    material = f"creatorproof.evm_signer.v1|{chain_id}|{address}".encode()
    return hashlib.sha256(material).hexdigest()


def issuer_key_fingerprint(signer) -> str | None:
    public_key_hex = str(getattr(signer, "public_key_hex", "") or "")
    if not public_key_hex:
        return None
    return hashlib.sha256(bytes.fromhex(public_key_hex)).hexdigest()


class _LeaseHeartbeat(threading.Thread):
    """Keep a claimed job and its signer mutex alive during slow finality waits."""

    def __init__(self, service: BlockchainAnchorService, job_id: str, token: str) -> None:
        super().__init__(name="creatorproof-blockchain-lease-heartbeat", daemon=True)
        self._service = service
        self._job_id = job_id
        self._token = token
        self._stop_event = threading.Event()
        self.lost = False

    def run(self) -> None:
        interval = max(1.0, self._service.settings.blockchain_anchor_lease_seconds / 3)
        while not self._stop_event.wait(interval):
            if not self._service._renew_claim(self._job_id, self._token):
                self.lost = True
                return

    def stop(self) -> None:
        self._stop_event.set()
        self.join(timeout=5)


class BlockchainAnchorService:
    """Own the durable transaction ledger and bridge it to one proof provider."""

    def __init__(
        self, *, session_factory, provider, transparency, settings, worker_id: str
    ) -> None:
        self._session_factory = session_factory
        self.provider = provider
        self.transparency = transparency
        self.settings = settings
        self.worker_id = worker_id
        self._deployment_id = deployment_id(settings)
        self._signer_lease_id = signer_lease_id(provider, settings)
        self._dispatch_lock = threading.Lock()
        self._claim_token: str | None = None

    @property
    def configured(self) -> bool:
        """Whether durable EVM work may be queued, independent of RPC health."""
        provider_name = str(getattr(self.provider, "name", "")).lower()
        if "attestation-service" in provider_name and hasattr(self.provider, "available"):
            return bool(self.provider.available)
        try:
            status = self.provider.status()
        except Exception:
            status = {}
        if "configured" in status:
            return bool(status["configured"])
        if status.get("available") is False:
            return False
        scope = str(status.get("scope") or "").upper()
        return (
            bool(status.get("is_blockchain"))
            or scope.startswith("PUBLIC_EVM_ATTESTATION")
            or "attestation-service" in str(getattr(self.provider, "name", "")).lower()
        )

    @property
    def enabled(self) -> bool:
        """Backward-compatible alias for durable queue configuration."""
        return self.configured

    @property
    def checkpoint_schema_configured(self) -> bool:
        """Whether the active provider has a distinct schema for checkpoint roots."""
        if hasattr(self.provider, "checkpoint_schema_uid"):
            return bool(self.provider.checkpoint_schema_uid)
        try:
            status = self.provider.status()
        except Exception:
            status = {}
        if "checkpoint_configured" in status:
            return bool(status["checkpoint_configured"])
        if "checkpoint_schema_uid" in status:
            return bool(status["checkpoint_schema_uid"])
        return bool(self.settings.eas_checkpoint_schema_uid)

    @property
    def checkpoint_enabled(self) -> bool:
        """Whether durable checkpoint jobs may be queued for this deployment."""
        return bool(
            self.configured
            and self.settings.blockchain_domain_anchoring_enabled
            and self.checkpoint_schema_configured
        )

    @property
    def counterparty_schema_configured(self) -> bool:
        """Whether a distinct schema exists for counterparty commitments."""
        if hasattr(self.provider, "coattestation_schema_uid"):
            return bool(self.provider.coattestation_schema_uid)
        return bool(self.settings.eas_coattestation_schema_uid)

    @property
    def counterparty_enabled(self) -> bool:
        """Whether a counterparty commitment can be queued for public anchoring."""
        return bool(
            self.configured
            and self.settings.blockchain_counterparty_attestation_enabled
            and self.counterparty_schema_configured
        )

    def enqueue_counterparty_attestation(
        self,
        *,
        body_hash: str,
        attestation_id: str,
        tenant_id: str,
        scan_id: str,
        signer_address: str,
        ref_uid: str | None,
    ) -> str | None:
        """Queue one counterparty commitment, bound to the platform attestation.

        The signature has already been verified and persisted, so a queue failure
        loses the public anchor, never the counterparty's commitment itself.
        """
        if not self.counterparty_enabled:
            return None
        return self.enqueue(
            commitment_hash=body_hash,
            commitment_type=BlockchainCommitmentType.COUNTERPARTY_ATTESTATION,
            subject_type="counterparty_attestation",
            subject_id=attestation_id,
            tenant_id=tenant_id,
            context={
                "scan_id": scan_id,
                "tenant_id": tenant_id,
                "counterparty_attestation_id": attestation_id,
                # Recorded for operators; the address is already inside the signed
                # body whose hash is the committed value.
                "signer_address": signer_address,
                "ref_uid": ref_uid,
            },
        )

    def enqueue(
        self,
        *,
        commitment_hash: str,
        commitment_type: BlockchainCommitmentType,
        subject_type: str,
        subject_id: str,
        tenant_id: str | None,
        context: dict | None = None,
    ) -> str | None:
        """Idempotently persist work before any RPC submission occurs."""
        if not self.enabled:
            return None
        from app.models import BlockchainAnchorJob

        digest = _normalized_hash(commitment_hash)
        db = self._session_factory()
        try:
            existing = db.scalar(
                select(BlockchainAnchorJob).where(
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.commitment_type == str(commitment_type),
                    BlockchainAnchorJob.commitment_hash_sha256 == digest,
                )
            )
            if existing is not None:
                return existing.id
            job = BlockchainAnchorJob(
                tenant_id=tenant_id,
                deployment_id=self._deployment_id,
                commitment_type=str(commitment_type),
                commitment_hash_sha256=digest,
                subject_type=subject_type,
                subject_id=subject_id,
                context=context or {},
                max_attempts=self.settings.blockchain_anchor_max_attempts,
            )
            db.add(job)
            db.commit()
            return job.id
        except IntegrityError:
            db.rollback()
            existing = db.scalar(
                select(BlockchainAnchorJob).where(
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.commitment_type == str(commitment_type),
                    BlockchainAnchorJob.commitment_hash_sha256 == digest,
                )
            )
            return existing.id if existing is not None else None
        finally:
            db.close()

    def enqueue_checkpoint(self, receipt: dict | None) -> str | None:
        checkpoint = (receipt or {}).get("checkpoint") or {}
        root = checkpoint.get("root_sha256")
        tree_size = checkpoint.get("tree_size")
        if not root or tree_size is None or not self.checkpoint_enabled:
            return None
        return self.enqueue(
            commitment_hash=str(root),
            commitment_type=BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT,
            subject_type="transparency_checkpoint",
            subject_id=f"{self.settings.transparency_log_id}:{tree_size}",
            tenant_id=None,
            context={
                "log_id": self.settings.transparency_log_id,
                "tree_size": int(tree_size),
                "checkpoint_signature_kid": checkpoint.get("signature_kid"),
                "checkpoint_signature_b64": checkpoint.get("signature_b64"),
            },
        )

    def anchor_packet(
        self,
        *,
        packet_hash: str,
        scan_id: str,
        tenant_id: str,
    ) -> ProofReceipt:
        """Submit a scan packet once, or resume its already prepared transaction."""
        if not self.enabled:
            return self.provider.anchor(packet_hash)
        job_id = self.enqueue(
            commitment_hash=packet_hash,
            commitment_type=BlockchainCommitmentType.EVIDENCE_PACKET,
            subject_type="scan",
            subject_id=scan_id,
            tenant_id=tenant_id,
            context={"scan_id": scan_id, "tenant_id": tenant_id},
        )
        if job_id is None:
            raise RuntimeError("Unable to create durable blockchain anchor job")
        self.process_job(job_id)
        return self.receipt_for_job(job_id)

    def receipt_for_job(self, job_id: str) -> ProofReceipt:
        from app.models import BlockchainAnchorJob

        db = self._session_factory()
        try:
            row = db.get(BlockchainAnchorJob, job_id)
            if row is None or row.deployment_id != self._deployment_id:
                raise LookupError(f"Unknown blockchain anchor job: {job_id}")
            envelope = row.receipt or {}
            status = envelope.get("status")
            if not status:
                status = (
                    AnchorStatus.FAILED
                    if row.state == BlockchainAnchorJobState.FAILED
                    else AnchorStatus.PENDING
                )
            return ProofReceipt(
                status=AnchorStatus(str(status)),
                provider=str(envelope.get("provider") or self.provider.name),
                receipt=envelope.get("receipt")
                or {
                    "anchor_scope": "PUBLIC_EVM_ATTESTATION",
                    "proof_kind": str(row.commitment_type),
                    "transaction_hash": row.transaction_hash,
                    "finalized": False,
                    "error_code": row.last_error,
                },
            )
        finally:
            db.close()

    def _prepared_callback(self, job_id: str, claim_token: str):
        def persist(metadata: dict) -> None:
            from app.models import BlockchainAnchorJob

            db = self._session_factory()
            try:
                row = db.get(BlockchainAnchorJob, job_id)
                if row is None or row.deployment_id != self._deployment_id:
                    raise LookupError(f"Unknown blockchain anchor job: {job_id}")
                if row.lease_owner != claim_token:
                    raise RuntimeError("BLOCKCHAIN_JOB_LEASE_LOST")
                transaction_hash = str(
                    metadata.get("transaction_hash") or metadata.get("tx_hash") or ""
                )
                signed_transaction_hex = metadata.get("signed_transaction_hex")
                nonce = metadata.get("nonce")
                chain_id = metadata.get("chain_id")
                prepared_identity = {
                    "transaction_hash": transaction_hash,
                    "signed_transaction_hex": signed_transaction_hex,
                    "transaction_nonce": int(nonce) if nonce is not None else None,
                    "chain_id": int(chain_id) if chain_id is not None else None,
                }
                if not transaction_hash or not signed_transaction_hex:
                    raise ValueError("Prepared transaction metadata is incomplete")
                for field, value in prepared_identity.items():
                    existing = getattr(row, field)
                    if existing is not None and existing != value:
                        raise RuntimeError(f"PREPARED_TRANSACTION_IDENTITY_MISMATCH:{field}")
                    setattr(row, field, value)
                row.state = BlockchainAnchorJobState.PREPARED
                row.updated_at = _utcnow()
                db.commit()
            finally:
                db.close()

        return persist

    def _ensure_signer_lease_row(self) -> None:
        from app.models import BlockchainSignerLease

        db = self._session_factory()
        try:
            if db.get(BlockchainSignerLease, self._signer_lease_id) is None:
                db.add(BlockchainSignerLease(deployment_id=self._signer_lease_id))
                db.commit()
        except IntegrityError:
            db.rollback()
        finally:
            db.close()

    def _claim_job(self, job_id: str) -> bool:
        """Atomically own one job and its EVM signer across processes."""
        from app.models import BlockchainAnchorJob, BlockchainSignerLease

        self._claim_token = None
        db = self._session_factory()
        now = _utcnow()
        token = f"{self.worker_id}:{uuid.uuid4().hex}"
        expiry = now + timedelta(seconds=self.settings.blockchain_anchor_lease_seconds)
        try:
            self._ensure_signer_lease_row()
            # A process can die after incrementing the final attempt but before a
            # transaction is prepared. Close that otherwise permanently-active row
            # once its lease expires. A persisted transaction hash is deliberately
            # excluded: it must remain reconcilable without allocating a new nonce.
            terminalized = db.execute(
                update(BlockchainAnchorJob)
                .where(
                    BlockchainAnchorJob.id == job_id,
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.state.in_(ACTIVE_JOB_STATES),
                    BlockchainAnchorJob.transaction_hash.is_(None),
                    BlockchainAnchorJob.attempts >= BlockchainAnchorJob.max_attempts,
                    or_(
                        BlockchainAnchorJob.lease_owner.is_(None),
                        BlockchainAnchorJob.lease_expires_at <= now,
                    ),
                )
                .values(
                    state=BlockchainAnchorJobState.FAILED,
                    last_error="BLOCKCHAIN_ANCHOR_ATTEMPTS_EXHAUSTED",
                    lease_owner=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            ).rowcount
            if terminalized:
                db.commit()
                return False

            signer_claimed = db.execute(
                update(BlockchainSignerLease)
                .where(
                    BlockchainSignerLease.deployment_id == self._signer_lease_id,
                    or_(
                        BlockchainSignerLease.lease_owner.is_(None),
                        BlockchainSignerLease.lease_expires_at <= now,
                    ),
                )
                .values(lease_owner=token, lease_expires_at=expiry, updated_at=now)
            ).rowcount
            if signer_claimed != 1:
                db.rollback()
                return False

            claimed = db.execute(
                update(BlockchainAnchorJob)
                .where(
                    BlockchainAnchorJob.id == job_id,
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.state.in_(ACTIVE_JOB_STATES),
                    BlockchainAnchorJob.available_at <= now,
                    or_(
                        BlockchainAnchorJob.attempts < BlockchainAnchorJob.max_attempts,
                        BlockchainAnchorJob.transaction_hash.is_not(None),
                    ),
                    or_(
                        BlockchainAnchorJob.lease_owner.is_(None),
                        BlockchainAnchorJob.lease_expires_at <= now,
                    ),
                )
                .values(
                    attempts=case(
                        (
                            BlockchainAnchorJob.attempts < BlockchainAnchorJob.max_attempts,
                            BlockchainAnchorJob.attempts + 1,
                        ),
                        else_=BlockchainAnchorJob.attempts,
                    ),
                    lease_owner=token,
                    lease_expires_at=expiry,
                    updated_at=now,
                )
            ).rowcount
            if claimed != 1:
                db.rollback()
                return False
            db.commit()
            self._claim_token = token
            return True
        except IntegrityError:
            db.rollback()
            return False
        finally:
            db.close()

    def _renew_claim(self, job_id: str, claim_token: str) -> bool:
        from app.models import BlockchainAnchorJob, BlockchainSignerLease

        db = self._session_factory()
        now = _utcnow()
        expiry = now + timedelta(seconds=self.settings.blockchain_anchor_lease_seconds)
        try:
            signer_renewed = db.execute(
                update(BlockchainSignerLease)
                .where(
                    BlockchainSignerLease.deployment_id == self._signer_lease_id,
                    BlockchainSignerLease.lease_owner == claim_token,
                )
                .values(lease_expires_at=expiry, updated_at=now)
            ).rowcount
            job_renewed = db.execute(
                update(BlockchainAnchorJob)
                .where(
                    BlockchainAnchorJob.id == job_id,
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.lease_owner == claim_token,
                    BlockchainAnchorJob.state.in_(ACTIVE_JOB_STATES),
                )
                .values(lease_expires_at=expiry, updated_at=now)
            ).rowcount
            if signer_renewed == 1 and job_renewed == 1:
                db.commit()
                return True
            db.rollback()
            return False
        finally:
            db.close()

    def _release_signer_lease(self, claim_token: str | None) -> None:
        if not claim_token:
            return
        from app.models import BlockchainSignerLease

        db = self._session_factory()
        try:
            db.execute(
                update(BlockchainSignerLease)
                .where(
                    BlockchainSignerLease.deployment_id == self._signer_lease_id,
                    BlockchainSignerLease.lease_owner == claim_token,
                )
                .values(lease_owner=None, lease_expires_at=None, updated_at=_utcnow())
            )
            db.commit()
        finally:
            db.close()

    def process_job(self, job_id: str) -> bool:
        """Submit/reconcile one job; every state transition is durable."""
        from app.models import BlockchainAnchorJob

        with self._dispatch_lock:
            if not self._claim_job(job_id):
                return False
            claim_token = self._claim_token
            if claim_token is None:  # pragma: no cover - invariant guard
                return False
            db = self._session_factory()
            try:
                row = db.get(BlockchainAnchorJob, job_id)
                if (
                    row is None
                    or row.deployment_id != self._deployment_id
                    or row.lease_owner != claim_token
                ):
                    self._release_signer_lease(claim_token)
                    return False
                tx_hash = row.transaction_hash
                commitment_hash = row.commitment_hash_sha256
                context = dict(row.context or {})
                context.update(
                    {
                        "commitment_type": row.commitment_type,
                        "subject_type": row.subject_type,
                        "subject_id": row.subject_id,
                    }
                )
                signed_transaction_hex = row.signed_transaction_hex
                commitment_type = row.commitment_type
            finally:
                db.close()

            heartbeat = _LeaseHeartbeat(self, job_id, claim_token)
            heartbeat.start()
            try:
                if tx_hash and hasattr(self.provider, "reconcile"):
                    receipt = self.provider.reconcile(
                        tx_hash,
                        commitment_hash,
                        expected_metadata=context,
                        signed_transaction_hex=signed_transaction_hex,
                    )
                else:
                    receipt = self.provider.anchor(
                        commitment_hash,
                        context=context,
                        commitment_type=commitment_type,
                        on_transaction_prepared=self._prepared_callback(job_id, claim_token),
                    )
                if heartbeat.lost:
                    logger.error("blockchain_job_lease_lost job_id=%s", job_id)
                    return False
                self._record_result(job_id, receipt, claim_token)
                return True
            except Exception as exc:
                self._record_failure(job_id, exc, claim_token)
                logger.warning(
                    "blockchain_anchor_attempt_failed job_id=%s error=%s",
                    job_id,
                    type(exc).__name__,
                )
                return False
            finally:
                heartbeat.stop()
                self._release_signer_lease(claim_token)
                self._claim_token = None

    def _record_result(
        self,
        job_id: str,
        receipt: ProofReceipt,
        claim_token: str,
    ) -> None:
        from app.models import BlockchainAnchorJob

        db = self._session_factory()
        try:
            row = db.scalar(
                select(BlockchainAnchorJob).where(
                    BlockchainAnchorJob.id == job_id,
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.lease_owner == claim_token,
                )
            )
            if row is None:
                return
            now = _utcnow()
            detail = dict(receipt.receipt or {})
            row.transaction_hash = (
                str(
                    detail.get("transaction_hash")
                    or detail.get("tx_hash")
                    or row.transaction_hash
                    or ""
                )
                or None
            )
            safe_detail = self._sanitize_receipt(detail)
            if "error_code" in safe_detail:
                safe_detail["error_code"] = self._safe_error_code(
                    safe_detail["error_code"], "BLOCKCHAIN_ANCHOR_FAILED"
                )
            row.last_error = None
            row.lease_owner = None
            row.lease_expires_at = None
            row.updated_at = now
            anchor_conditions_met = detail.get("anchor_conditions_met")
            if anchor_conditions_met is None:
                # Backward-compatible input for providers that predate the more
                # precise condition name. Never default missing evidence to true.
                anchor_conditions_met = detail.get("finalized") is True
            receipt_binding_error = None
            if str(receipt.status) == str(AnchorStatus.ANCHORED) and anchor_conditions_met:
                receipt_hash = self._receipt_commitment_hash(detail)
                if receipt_hash is None:
                    receipt_binding_error = "RECEIPT_COMMITMENT_MISSING_OR_CONFLICTING"
                elif receipt_hash != row.commitment_hash_sha256:
                    receipt_binding_error = "RECEIPT_COMMITMENT_MISMATCH"
            if (
                str(receipt.status) == str(AnchorStatus.ANCHORED)
                and anchor_conditions_met
                and receipt_binding_error is None
            ):
                row.state = BlockchainAnchorJobState.CONFIRMED
                row.confirmed_at = now
            elif str(receipt.status) == str(AnchorStatus.FAILED):
                row.state = (
                    BlockchainAnchorJobState.RETRYABLE
                    if row.transaction_hash or row.attempts < row.max_attempts
                    else BlockchainAnchorJobState.FAILED
                )
                row.last_error = self._safe_error_code(
                    detail.get("error_code"), "BLOCKCHAIN_ANCHOR_FAILED"
                )
            else:
                row.state = BlockchainAnchorJobState.SUBMITTED
                # Waiting for public-chain finality is not a failed attempt and
                # must not exhaust the retry budget.
                row.attempts = max(0, row.attempts - 1)
                row.submitted_at = row.submitted_at or now
            if receipt_binding_error is not None:
                row.state = (
                    BlockchainAnchorJobState.RETRYABLE
                    if row.transaction_hash or row.attempts < row.max_attempts
                    else BlockchainAnchorJobState.FAILED
                )
                row.last_error = receipt_binding_error
                safe_detail["error_code"] = receipt_binding_error
                safe_detail["anchor_conditions_met"] = False
            effective_status = (
                AnchorStatus.ANCHORED
                if row.state == BlockchainAnchorJobState.CONFIRMED
                else (
                    AnchorStatus.FAILED
                    if row.state == BlockchainAnchorJobState.FAILED
                    else AnchorStatus.PENDING
                )
            )
            row.receipt = {
                "status": str(effective_status),
                "provider": receipt.provider,
                "receipt": safe_detail,
            }
            if row.state != BlockchainAnchorJobState.CONFIRMED:
                row.available_at = now + timedelta(
                    seconds=self.settings.blockchain_anchor_retry_backoff_seconds
                    * max(1, 2 ** min(row.attempts - 1, 6))
                )
            if row.state == BlockchainAnchorJobState.CONFIRMED and str(row.commitment_type) == str(
                BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT
            ):
                external = self._checkpoint_external_commitment(row)
                self.transparency.attach_external_commitment(
                    db,
                    tree_size=int((row.context or {}).get("tree_size", 0)),
                    root_sha256=row.commitment_hash_sha256,
                    external_commitment=external,
                )
            self._apply_subject_receipt(db, row)
            db.commit()
            METRICS.increment(
                "creatorproof_blockchain_anchor_total",
                commitment_type=row.commitment_type,
                state=str(row.state),
            )
        finally:
            db.close()

    @staticmethod
    def _receipt_commitment_hash(detail: dict) -> str | None:
        """Return one unambiguous receipt commitment, including legacy field names."""
        fields = (
            "commitment_hash_sha256",
            "packet_hash_sha256",
            "checkpoint_hash_sha256",
            "coattestation_hash_sha256",
        )
        values = [detail.get(field) for field in fields if detail.get(field) not in (None, "")]
        if not values:
            return None
        try:
            normalized = {_normalized_hash(str(value)) for value in values}
        except (TypeError, ValueError):
            return None
        return next(iter(normalized)) if len(normalized) == 1 else None

    @staticmethod
    def _safe_error_code(value: object, fallback: str) -> str:
        """Keep public/durable failures machine-readable without echoing secret-bearing text."""
        code = str(value or "")
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_:-.")
        return code if 0 < len(code) <= 160 and set(code) <= allowed else fallback

    def _checkpoint_external_commitment(self, job) -> dict:
        """Build a portable, terminology-safe receipt for a signed tree head."""
        context = dict(job.context or {})
        if context.get("log_id") != self.settings.transparency_log_id:
            raise RuntimeError("checkpoint job log id does not match this deployment")
        tree_size = int(context.get("tree_size", 0))
        if tree_size < 1:
            raise RuntimeError("checkpoint job has an invalid tree size")
        detail = dict((job.receipt or {}).get("receipt") or {})
        if self._receipt_commitment_hash(detail) != job.commitment_hash_sha256:
            raise RuntimeError("checkpoint receipt does not bind its queued root")

        depth_reached = detail.get("confirmation_depth_reached")
        if depth_reached is None:
            depth_reached = detail.get("finality_reached")
        if detail.get("finalized_block_verified") is True:
            protocol_finality_state = "FINALIZED_BLOCK_VERIFIED"
        elif detail.get("safe_block_verified") is True:
            protocol_finality_state = "SAFE_BLOCK_VERIFIED"
        else:
            protocol_finality_state = "NOT_VERIFIED"
        portable_detail = self._sanitize_receipt(detail)
        if "finality_reached" in portable_detail:
            portable_detail["confirmation_depth_reached"] = portable_detail.pop("finality_reached")
        # Older receipts used `finalized` for an application confirmation policy,
        # not consensus-protocol finality. Preserve the fact under an honest name.
        if "finalized" in portable_detail:
            legacy_finalized = portable_detail.pop("finalized")
            portable_detail.setdefault("anchor_conditions_met", legacy_finalized)
        finality_policy = str(detail.get("finality_policy") or self.settings.eas_finality_policy)
        return {
            "schema": "creatorproof.checkpoint_external_commitment.v1",
            "confirmation_state": "CONFIRMED",
            "confirmation_basis": "CANONICAL_RECEIPT_AND_" + finality_policy.upper(),
            "finality_policy": finality_policy,
            "protocol_finality_state": protocol_finality_state,
            "deployment_id": job.deployment_id,
            "log_id": context["log_id"],
            "tree_size": tree_size,
            "root_sha256": job.commitment_hash_sha256,
            "provider": (job.receipt or {}).get("provider") or self.provider.name,
            "confirmed_at": job.confirmed_at.isoformat() if job.confirmed_at else None,
            "confirmation_depth": {
                "observed": detail.get("confirmations"),
                "required": detail.get("required_confirmations"),
                "reached": depth_reached,
            },
            "receipt": portable_detail,
        }

    @staticmethod
    def _sanitize_receipt(receipt: dict) -> dict:
        """Persist/export no signed transaction bytes or accidentally nested secrets."""
        forbidden = {
            "signed_transaction_hex",
            "raw_transaction",
            "private_key",
            "eas_private_key",
            "rpc_url",
            "rpc_urls",
            "authorization",
            "api_key",
            "access_token",
            "refresh_token",
            "password",
        }
        forbidden_squashed = {item.replace("_", "") for item in forbidden}

        def forbidden_key(value: object) -> bool:
            normalized = "".join(
                character.lower() if character.isalnum() else "_" for character in str(value)
            ).strip("_")
            squashed = normalized.replace("_", "")
            return normalized in forbidden or squashed in forbidden_squashed

        def scrub(value):
            if isinstance(value, dict):
                return {key: scrub(item) for key, item in value.items() if not forbidden_key(key)}
            if isinstance(value, list):
                return [scrub(item) for item in value]
            return value

        return scrub(receipt)

    def _record_failure(self, job_id: str, exc: Exception, claim_token: str) -> None:
        from app.models import BlockchainAnchorJob

        db = self._session_factory()
        try:
            row = db.scalar(
                select(BlockchainAnchorJob).where(
                    BlockchainAnchorJob.id == job_id,
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.lease_owner == claim_token,
                )
            )
            if row is None:
                return
            now = _utcnow()
            row.last_error = f"BLOCKCHAIN_ANCHOR_EXCEPTION:{type(exc).__name__}"
            row.state = (
                BlockchainAnchorJobState.RETRYABLE
                if row.transaction_hash or row.attempts < row.max_attempts
                else BlockchainAnchorJobState.FAILED
            )
            row.lease_owner = None
            row.lease_expires_at = None
            row.available_at = now + timedelta(
                seconds=self.settings.blockchain_anchor_retry_backoff_seconds
                * max(1, 2 ** min(row.attempts - 1, 6))
            )
            row.updated_at = now
            db.commit()
        finally:
            db.close()

    def _apply_counterparty_receipt(self, db, job) -> None:
        """Move one counterparty commitment to its terminal anchoring state."""
        from app.domain.platform import CounterpartyAttestationState
        from app.models import CounterpartyAttestation
        from app.services.tenancy import bind_tenant_context

        bind_tenant_context(db, job.tenant_id)
        row = db.get(CounterpartyAttestation, job.subject_id)
        if row is None or row.state == CounterpartyAttestationState.WITHDRAWN:
            return
        envelope = job.receipt or {}
        detail = dict(envelope.get("receipt") or {})
        if str(job.state) == str(BlockchainAnchorJobState.CONFIRMED):
            row.state = str(CounterpartyAttestationState.ANCHORED)
            row.platform_attestation_uid = row.platform_attestation_uid or detail.get("ref_uid")
        elif str(job.state) == str(BlockchainAnchorJobState.FAILED):
            row.state = str(CounterpartyAttestationState.ANCHOR_FAILED)
        else:
            row.state = str(CounterpartyAttestationState.ANCHOR_PENDING)

    def _apply_subject_receipt(self, db, job) -> None:
        if job.subject_type == "counterparty_attestation" and job.receipt:
            self._apply_counterparty_receipt(db, job)
            return
        if job.subject_type != "scan" or not job.receipt:
            return
        from app.domain.platform import ScanLifecycleState
        from app.models import Scan
        from app.services.orchestration import TOPIC_SCAN_ACCEPTED, enqueue_outbox
        from app.services.tenancy import bind_tenant_context

        bind_tenant_context(db, job.tenant_id)
        scan = db.get(Scan, job.subject_id)
        if scan is None or not scan.evidence_packet:
            return
        envelope = job.receipt
        packet = dict(scan.evidence_packet)
        proof = dict(packet.get("proof") or {})
        proof.update(
            {
                "anchor_status": envelope.get("status"),
                "provider": envelope.get("provider"),
                "receipt": envelope.get("receipt"),
            }
        )
        packet["proof"] = proof
        scan.evidence_packet = packet
        scan.anchor_status = str(envelope.get("status"))
        if (
            self.settings.proof_require_chain
            and str(job.state) == str(BlockchainAnchorJobState.CONFIRMED)
            and str(envelope.get("status")) == str(AnchorStatus.ANCHORED)
        ):
            # In strict mode the scan's evidence result may be available earlier,
            # but the lifecycle does not become COMPLETE until durable recovery
            # has observed a confirmed chain binding.
            scan.lifecycle_state = str(ScanLifecycleState.COMPLETED)
            # Wake the scan runner so its retryable PROOF stage and pending
            # NOTIFY/review work complete after asynchronous chain confirmation.
            # Stage compare-and-set makes duplicate recovery deliveries harmless.
            enqueue_outbox(
                db,
                tenant_id=scan.tenant_id,
                topic=TOPIC_SCAN_ACCEPTED,
                payload={
                    "scan_id": scan.id,
                    "recovery": True,
                    "reason": "PUBLIC_CHAIN_CONFIRMED",
                },
            )

    def dispatch_once(self, batch_size: int = 16) -> int:
        from app.models import BlockchainAnchorJob

        self.reconcile_unlogged_records(batch_size=batch_size)
        self.flush_due_checkpoint()
        self.reconcile_checkpoint_external_commitments(batch_size=batch_size)
        self.reconcile_unqueued_checkpoints(batch_size=batch_size)
        self.reconcile_unanchored_counterparty_attestations(batch_size=batch_size)
        if not self.enabled:
            return 0
        db = self._session_factory()
        try:
            now = _utcnow()
            statement = (
                select(BlockchainAnchorJob)
                .where(
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.state.in_(ACTIVE_JOB_STATES),
                    BlockchainAnchorJob.available_at <= now,
                    or_(
                        BlockchainAnchorJob.lease_owner.is_(None),
                        BlockchainAnchorJob.lease_expires_at <= now,
                    ),
                )
                .order_by(BlockchainAnchorJob.created_at)
                .limit(batch_size)
            )
            if db.get_bind().dialect.name == "postgresql":
                statement = statement.with_for_update(skip_locked=True)
            job_ids = [row.id for row in db.scalars(statement).all()]
        finally:
            db.close()
        return sum(1 for job_id in job_ids if self.process_job(job_id))

    def flush_due_checkpoint(self) -> str | None:
        """Close a stale partial transparency batch and queue its signed root."""
        db = self._session_factory()
        try:
            checkpoint = self.transparency.flush_due_checkpoint(
                db,
                max_age_seconds=self.settings.transparency_checkpoint_max_age_seconds,
            )
        finally:
            db.close()
        if checkpoint is None:
            return None
        return self.enqueue_checkpoint({"checkpoint": checkpoint})

    def reconcile_checkpoint_external_commitments(self, batch_size: int = 32) -> int:
        """Backfill portable receipts for confirmations committed before attachment."""
        from app.models import BlockchainAnchorJob, TransparencyCheckpoint

        db = self._session_factory()
        attached = 0
        try:
            jobs = db.scalars(
                select(BlockchainAnchorJob)
                .join(
                    TransparencyCheckpoint,
                    (TransparencyCheckpoint.log_id == self.settings.transparency_log_id)
                    & (
                        TransparencyCheckpoint.root_sha256
                        == BlockchainAnchorJob.commitment_hash_sha256
                    ),
                )
                .where(
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.commitment_type
                    == str(BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT),
                    BlockchainAnchorJob.state == BlockchainAnchorJobState.CONFIRMED,
                    TransparencyCheckpoint.external_commitment.is_(None),
                )
                .order_by(BlockchainAnchorJob.confirmed_at)
                .limit(batch_size)
            ).all()
            for job in jobs:
                try:
                    external = self._checkpoint_external_commitment(job)
                    self.transparency.attach_external_commitment(
                        db,
                        tree_size=int((job.context or {}).get("tree_size", 0)),
                        root_sha256=job.commitment_hash_sha256,
                        external_commitment=external,
                    )
                    db.commit()
                    attached += 1
                except Exception:
                    db.rollback()
                    logger.exception(
                        "checkpoint_external_commitment_reconcile_failed job_id=%s",
                        job.id,
                    )
            return attached
        finally:
            db.close()

    def _recover_model_rows(self, model, *, batch_size: int, label: str) -> int:
        """Append signed rows committed immediately before a process crash."""
        from app.models import TransparencyLeaf
        from app.services.tenancy import bind_break_glass

        db = self._session_factory()
        appended = 0
        try:
            bind_break_glass(db, enabled=True)
            rows = db.scalars(
                select(model)
                .outerjoin(
                    TransparencyLeaf,
                    (TransparencyLeaf.log_id == self.settings.transparency_log_id)
                    & (TransparencyLeaf.statement_id == model.id),
                )
                .where(TransparencyLeaf.id.is_(None))
                .order_by(model.created_at)
                .limit(batch_size)
            ).all()
            for row in rows:
                try:
                    receipt = self.transparency.append(
                        db,
                        packet_hash=row.payload_digest_sha256,
                        statement_id=row.id,
                    )
                    self.enqueue_checkpoint(receipt)
                    appended += 1
                except Exception:
                    db.rollback()
                    logger.exception(
                        "%s_log_reconcile_failed record_id=%s",
                        label,
                        row.id,
                    )
                    break
            return appended
        finally:
            db.close()

    def reconcile_unlogged_records(self, batch_size: int = 32) -> int:
        """Recover domain events and evidence statements missing a log leaf."""
        from app.models import EvidenceStatement, IntegrityEvent

        recovered = self._recover_model_rows(
            IntegrityEvent,
            batch_size=batch_size,
            label="integrity_event",
        )
        recovered += self._recover_model_rows(
            EvidenceStatement,
            batch_size=batch_size,
            label="evidence_statement",
        )
        return recovered

    # Kept for operational callers introduced alongside the original worker.
    def reconcile_unlogged_integrity_events(self, batch_size: int = 32) -> int:
        from app.models import IntegrityEvent

        return self._recover_model_rows(
            IntegrityEvent,
            batch_size=batch_size,
            label="integrity_event",
        )

    def reconcile_unanchored_counterparty_attestations(self, batch_size: int = 32) -> int:
        """Queue commitments whose signature was stored just before a crash."""
        from app.domain.platform import CounterpartyAttestationState
        from app.models import CounterpartyAttestation
        from app.services.tenancy import bind_break_glass

        if not self.counterparty_enabled:
            return 0
        db = self._session_factory()
        queued = 0
        try:
            bind_break_glass(db, enabled=True)
            rows = db.scalars(
                select(CounterpartyAttestation)
                .where(
                    CounterpartyAttestation.anchor_job_id.is_(None),
                    CounterpartyAttestation.state == str(CounterpartyAttestationState.SIGNED),
                )
                .order_by(CounterpartyAttestation.created_at)
                .limit(batch_size)
            ).all()
            for row in rows:
                job_id = self.enqueue_counterparty_attestation(
                    body_hash=row.body_hash_sha256,
                    attestation_id=row.id,
                    tenant_id=row.tenant_id,
                    scan_id=row.scan_id,
                    signer_address=row.signer_address,
                    ref_uid=row.platform_attestation_uid,
                )
                if job_id is None:
                    continue
                row.anchor_job_id = job_id
                row.state = str(CounterpartyAttestationState.ANCHOR_PENDING)
                db.commit()
                queued += 1
            return queued
        finally:
            db.close()

    def reconcile_unqueued_checkpoints(self, batch_size: int = 32) -> int:
        """Recover signed checkpoints committed before their outbox job existed."""
        from app.models import BlockchainAnchorJob, TransparencyCheckpoint

        if not self.checkpoint_enabled:
            return 0
        db = self._session_factory()
        queued = 0
        try:
            rows = db.scalars(
                select(TransparencyCheckpoint)
                .outerjoin(
                    BlockchainAnchorJob,
                    (BlockchainAnchorJob.deployment_id == self._deployment_id)
                    & (
                        BlockchainAnchorJob.commitment_type
                        == str(BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT)
                    )
                    & (
                        BlockchainAnchorJob.commitment_hash_sha256
                        == TransparencyCheckpoint.root_sha256
                    ),
                )
                .where(
                    TransparencyCheckpoint.log_id == self.settings.transparency_log_id,
                    BlockchainAnchorJob.id.is_(None),
                )
                .order_by(TransparencyCheckpoint.tree_size)
                .limit(batch_size)
            ).all()
            for checkpoint in rows:
                job_id = self.enqueue_checkpoint(
                    {
                        "checkpoint": {
                            "tree_size": checkpoint.tree_size,
                            "root_sha256": checkpoint.root_sha256,
                            "signature_kid": checkpoint.signature_kid,
                            "signature_b64": checkpoint.signature_b64,
                        }
                    }
                )
                if job_id is not None:
                    queued += 1
            return queued
        finally:
            db.close()

    def status(self) -> dict[str, Any]:
        from app.models import BlockchainAnchorJob

        try:
            provider_status = self.provider.status()
        except Exception:
            provider_status = {}
        configured = self.configured
        live_write_ready = provider_status.get("live_write_ready")
        live_write_reason = provider_status.get("live_write_reason")
        if not configured:
            live_write_ready = False
            live_write_reason = live_write_reason or provider_status.get("reason")
        checkpoint_schema_configured = self.checkpoint_schema_configured
        checkpoint_writes_enabled = bool(
            configured
            and self.settings.blockchain_domain_anchoring_enabled
            and checkpoint_schema_configured
        )
        db = self._session_factory()
        try:
            counts = {
                str(state): int(count)
                for state, count in db.execute(
                    select(BlockchainAnchorJob.state, func.count(BlockchainAnchorJob.id))
                    .where(BlockchainAnchorJob.deployment_id == self._deployment_id)
                    .group_by(BlockchainAnchorJob.state)
                ).all()
            }
            oldest = db.scalar(
                select(func.min(BlockchainAnchorJob.created_at)).where(
                    BlockchainAnchorJob.deployment_id == self._deployment_id,
                    BlockchainAnchorJob.state.in_(
                        [
                            BlockchainAnchorJobState.PENDING,
                            BlockchainAnchorJobState.PREPARED,
                            BlockchainAnchorJobState.SUBMITTED,
                            BlockchainAnchorJobState.RETRYABLE,
                        ]
                    ),
                )
            )
            return {
                "enabled": configured,
                "provider_configured": configured,
                "durable_queue_enabled": configured,
                # `enabled` describes configuration; readiness is intentionally
                # separate so a temporary RPC outage never disables outbox recovery.
                "chain_writes_configured": configured,
                "chain_writes_enabled": live_write_ready is True,
                "chain_writes_ready": live_write_ready is True,
                "live_write_ready": live_write_ready,
                "live_write_reason": live_write_reason,
                "live_write_checked_at": provider_status.get("live_write_checked_at"),
                "checkpoint_schema_configured": checkpoint_schema_configured,
                "checkpoint_writes_enabled": checkpoint_writes_enabled,
                "checkpoint_writes_ready": checkpoint_writes_enabled and live_write_ready is True,
                "counterparty_schema_configured": self.counterparty_schema_configured,
                "counterparty_writes_enabled": self.counterparty_enabled,
                "counterparty_writes_ready": self.counterparty_enabled and live_write_ready is True,
                "deployment_id": self._deployment_id,
                "signer_lease_id": self._signer_lease_id,
                "states": counts,
                "oldest_pending_at": oldest.isoformat() if oldest else None,
            }
        finally:
            db.close()


class BlockchainDispatcherThread(threading.Thread):
    def __init__(self, service: BlockchainAnchorService, interval_seconds: float) -> None:
        super().__init__(name="creatorproof-blockchain-dispatch", daemon=True)
        self._service = service
        self._interval = interval_seconds
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._service.dispatch_once()
            except Exception:  # pragma: no cover - defensive isolation
                logger.exception("blockchain_dispatch_iteration_failed")
            self._stop_event.wait(self._interval)

    def stop(self) -> None:
        self._stop_event.set()


def prepare_integrity_event(
    db,
    *,
    signer,
    tenant_id: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    attributes: dict,
) -> Any:
    """Add a signed event to the caller's business transaction without committing it."""
    from app.models import IntegrityEvent, new_id

    event_id = new_id("iev")
    payload = {
        "schema": INTEGRITY_EVENT_SCHEMA,
        "event_id": event_id,
        "event_type": event_type,
        "tenant_id": tenant_id,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "created_at": _utcnow().isoformat(),
        "attributes": attributes,
    }
    signed = signer.sign(payload)
    row = IntegrityEvent(
        id=event_id,
        tenant_id=tenant_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        payload=payload,
        payload_digest_sha256=signed["payload_digest_sha256"],
        signature_kid=signed["signature_kid"],
        signature_alg=signed["signature_alg"],
        signature_b64=signed["signature_b64"],
        cose_sign1_b64=signed["cose_sign1_b64"],
    )
    db.add(row)
    return row


def append_integrity_event(
    db,
    *,
    event,
    transparency,
    blockchain: BlockchainAnchorService | None,
) -> dict:
    """Append a committed event to the log; recovery retries this after crashes."""
    from app.models import TransparencyLeaf

    existing = db.scalar(
        select(TransparencyLeaf).where(TransparencyLeaf.statement_id == event.id).limit(1)
    )
    if existing is not None:
        proof = transparency.inclusion_proof(db, leaf_index=existing.leaf_index) or {}
        return {
            "event_id": event.id,
            "payload_digest_sha256": event.payload_digest_sha256,
            "transparency": proof,
            "blockchain_anchor_job_id": None,
        }
    receipt = transparency.append(
        db,
        packet_hash=event.payload_digest_sha256,
        statement_id=event.id,
    )
    anchor_job_id = blockchain.enqueue_checkpoint(receipt) if blockchain else None
    return {
        "event_id": event.id,
        "payload_digest_sha256": event.payload_digest_sha256,
        "signature_kid": event.signature_kid,
        "transparency": receipt,
        "blockchain_anchor_job_id": anchor_job_id,
    }


def record_integrity_event(
    db,
    *,
    signer,
    transparency,
    blockchain: BlockchainAnchorService | None,
    tenant_id: str,
    event_type: str,
    subject_type: str,
    subject_id: str,
    attributes: dict,
) -> dict:
    """Persist, sign, log and enqueue one material domain event."""
    event = prepare_integrity_event(
        db,
        signer=signer,
        tenant_id=tenant_id,
        event_type=event_type,
        subject_type=subject_type,
        subject_id=subject_id,
        attributes=attributes,
    )
    db.commit()
    return append_integrity_event(
        db,
        event=event,
        transparency=transparency,
        blockchain=blockchain,
    )
