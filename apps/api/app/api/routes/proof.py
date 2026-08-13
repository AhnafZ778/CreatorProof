"""Proof and transparency inspection.

These endpoints exist so a judge or auditor can check the anchoring layer
directly. They deliberately keep two things separate: a public EVM attestation of
the canonical packet hash, and a local append-only transparency receipt, which is
not a blockchain.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_container, get_db, require_any_scope, require_scope
from app.container import Container
from app.core.security import AuthContext
from app.domain.platform import BlockchainAnchorJobState, CredentialScope
from app.models import (
    BlockchainAnchorJob,
    IntegrityEvent,
    SigningKey,
    TransparencyCheckpoint,
    TransparencyLeaf,
)
from app.schemas import TransparencyConsistencyRead

router = APIRouter(prefix="/v1/proof", tags=["proof"])

_ACTIVE_CHECKPOINT_STATES = {
    str(BlockchainAnchorJobState.PENDING),
    str(BlockchainAnchorJobState.PREPARED),
    str(BlockchainAnchorJobState.SUBMITTED),
    str(BlockchainAnchorJobState.RETRYABLE),
}

_PROOF_READ_SCOPES = (
    CredentialScope.SCANS_READ,
    CredentialScope.WORKS_READ,
    CredentialScope.RIGHTS_READ,
    CredentialScope.REVIEW_READ,
)

_SUBJECT_SCOPE = {
    "scan": CredentialScope.SCANS_READ,
    "work": CredentialScope.WORKS_READ,
    "party": CredentialScope.RIGHTS_READ,
    "claim": CredentialScope.RIGHTS_READ,
    "license": CredentialScope.RIGHTS_READ,
    "policy_version": CredentialScope.RIGHTS_READ,
    "review_case": CredentialScope.REVIEW_READ,
}


def _normalize_sha256(value: str) -> str:
    normalized = value.removeprefix("0x").lower()
    try:
        if len(bytes.fromhex(normalized)) != 32:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INVALID_COMMITMENT_HASH",
                "message": "Expected commitment must be a 32-byte hexadecimal SHA-256 digest.",
            },
        ) from exc
    return normalized


def _checkpoint_tree_size(job: BlockchainAnchorJob) -> int | None:
    try:
        value = int((job.context or {}).get("tree_size", 0))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _receipt_commitment(receipt: dict) -> str | None:
    value = receipt.get("checkpoint_hash_sha256") or receipt.get("commitment_hash_sha256")
    if not value:
        return None
    normalized = str(value).removeprefix("0x").lower()
    try:
        if len(bytes.fromhex(normalized)) != 32:
            return None
    except ValueError:
        return None
    return normalized


def _receipt_anchor_conditions_met(receipt: dict) -> bool:
    explicit = receipt.get("anchor_conditions_met")
    return bool(explicit if explicit is not None else receipt.get("finalized") is True)


def _portable_receipt(receipt: dict) -> dict:
    result = dict(receipt)
    if "finality_reached" in result:
        result["confirmation_depth_reached"] = result.pop("finality_reached")
    if "finalized" in result:
        legacy_finalized = result.pop("finalized")
        result.setdefault("anchor_conditions_met", legacy_finalized)
    return result


@router.get("/status")
def proof_status(
    auth: Annotated[
        AuthContext,
        Depends(require_any_scope(*_PROOF_READ_SCOPES)),
    ],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    del auth
    status_payload = container.proof_anchor.status()
    ledger_status = container.blockchain.status()
    chain_writes_enabled = bool(
        ledger_status.get("chain_writes_enabled", ledger_status.get("chain_writes_ready", False))
    )
    chain_provider_configured = bool(
        ledger_status.get(
            "chain_writes_configured",
            ledger_status.get("provider_configured", container.blockchain.enabled),
        )
    )
    return {
        **status_payload,
        "transaction_ledger": ledger_status,
        "requires_chain": container.settings.proof_require_chain,
        # A configured EAS-shaped provider is not an active blockchain
        # deployment when its dependencies or deployment tuple are unavailable.
        "is_blockchain": chain_writes_enabled,
        "chain_writes_enabled": chain_writes_enabled,
        "chain_provider_configured": chain_provider_configured,
        # Kept RPC-free; /v1/network/status reads the registry contract itself.
        "multi_party_attestation": {
            "enabled": container.settings.blockchain_counterparty_attestation_enabled,
            "counterparty_writes_enabled": ledger_status.get("counterparty_writes_enabled", False),
            "status_endpoint": "/v1/network/status",
        },
        "committed_value": "bytes32 packetHash",
        "on_chain_data": ["canonical evidence packet hash"],
        "batched_on_chain_data": ["signed transparency checkpoint root"],
        "never_on_chain": [
            "candidate or reference media",
            "detector outputs and scores",
            "claimant identity and rights records",
            "tenant identifiers",
        ],
        "statement": (
            "A public EVM attestation commits the packet identity and its time. It does "
            "not establish that the underlying evidence or any rights claim is true."
            if chain_writes_enabled
            else "This deployment records a local append-only transparency receipt. "
            "It is cryptographic audit infrastructure, not a blockchain."
        ),
    }


@router.get("/integrity/{subject_type}/{subject_id}")
def subject_integrity(
    subject_type: str,
    subject_id: str,
    auth: Annotated[
        AuthContext,
        Depends(require_any_scope(*_PROOF_READ_SCOPES)),
    ],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Return signed domain history and its cheapest available public-chain binding."""
    required_scope = _SUBJECT_SCOPE.get(subject_type)
    if required_scope is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_INTEGRITY_SUBJECT_TYPE", "subject_type": subject_type},
        )
    if not auth.has_scope(required_scope):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "INSUFFICIENT_SCOPE",
                "message": f"This subject requires the '{required_scope.value}' permission.",
                "required_scope": required_scope.value,
            },
        )
    events = list(
        db.scalars(
            select(IntegrityEvent)
            .where(
                IntegrityEvent.tenant_id == auth.tenant_id,
                IntegrityEvent.subject_type == subject_type,
                IntegrityEvent.subject_id == subject_id,
            )
            .order_by(IntegrityEvent.created_at)
        ).all()
    )
    if not events:
        raise HTTPException(status_code=404, detail="No integrity history for this subject")

    ledger_status = container.blockchain.status()
    checkpoint_jobs = list(
        db.scalars(
            select(BlockchainAnchorJob)
            .where(
                BlockchainAnchorJob.subject_type == "transparency_checkpoint",
                BlockchainAnchorJob.deployment_id == ledger_status["deployment_id"],
            )
            .order_by(BlockchainAnchorJob.created_at)
        ).all()
    )
    checkpoints = list(
        db.scalars(
            select(TransparencyCheckpoint)
            .where(TransparencyCheckpoint.log_id == container.transparency.log_id)
            .order_by(TransparencyCheckpoint.tree_size)
        ).all()
    )
    checkpoints_by_size = {checkpoint.tree_size: checkpoint for checkpoint in checkpoints}
    items = []
    for event in events:
        leaf = db.scalar(
            select(TransparencyLeaf).where(TransparencyLeaf.statement_id == event.id).limit(1)
        )
        qualifying = sorted(
            [
                job
                for job in checkpoint_jobs
                if (
                    leaf is not None
                    and (job.context or {}).get("log_id") == container.transparency.log_id
                    and (_checkpoint_tree_size(job) or 0) > leaf.leaf_index
                )
            ],
            key=lambda job: _checkpoint_tree_size(job) or 0,
        )
        confirmed_anchor = None
        confirmed_inclusion = None
        confirmed_checks = None
        invalid_confirmations: list[dict] = []
        for candidate in qualifying:
            if str(candidate.state) != str(BlockchainAnchorJobState.CONFIRMED):
                continue
            tree_size = _checkpoint_tree_size(candidate)
            if leaf is None or tree_size is None:
                continue
            inclusion = container.transparency.inclusion_proof(
                db,
                leaf_index=leaf.leaf_index,
                tree_size=tree_size,
            )
            receipt = dict((candidate.receipt or {}).get("receipt") or {})
            checkpoint = checkpoints_by_size.get(tree_size)
            checks = {
                "inclusion_proof_valid": bool(
                    inclusion
                    and container.transparency.verify_inclusion(
                        leaf.packet_hash_sha256,
                        inclusion["root_sha256"],
                        inclusion["inclusion_proof"],
                    )
                ),
                "computed_root_matches_queued_commitment": bool(
                    inclusion and inclusion["root_sha256"] == candidate.commitment_hash_sha256
                ),
                "on_chain_receipt_matches_queued_commitment": (
                    _receipt_commitment(receipt) == candidate.commitment_hash_sha256
                ),
                "signed_checkpoint_matches_queued_commitment": bool(
                    checkpoint and checkpoint.root_sha256 == candidate.commitment_hash_sha256
                ),
                "anchor_conditions_met": _receipt_anchor_conditions_met(receipt),
            }
            if all(checks.values()):
                confirmed_anchor = candidate
                confirmed_inclusion = inclusion
                confirmed_checks = checks
                break
            invalid_confirmations.append(
                {"job_id": candidate.id, "tree_size": tree_size, "checks": checks}
            )

        local_checkpoint = None
        if leaf is not None:
            local_checkpoint = next(
                (
                    checkpoint
                    for checkpoint in checkpoints
                    if checkpoint.tree_size > leaf.leaf_index
                ),
                None,
            )
        tree_size = (
            _checkpoint_tree_size(confirmed_anchor)
            if confirmed_anchor is not None
            else (local_checkpoint.tree_size if local_checkpoint is not None else None)
        )
        transparency = None
        if leaf is not None:
            inclusion = confirmed_inclusion or container.transparency.inclusion_proof(
                db, leaf_index=leaf.leaf_index, tree_size=tree_size
            )
            if inclusion is not None:
                transparency = {
                    "log_id": container.transparency.log_id,
                    "packet_hash_sha256": leaf.packet_hash_sha256,
                    "leaf_hash_sha256": leaf.leaf_hash_sha256,
                    "inclusion_verified": container.transparency.verify_inclusion(
                        leaf.packet_hash_sha256,
                        inclusion["root_sha256"],
                        inclusion["inclusion_proof"],
                    ),
                    "signed_checkpoint": bool(
                        checkpoints_by_size.get(inclusion["tree_size"])
                        and checkpoints_by_size[inclusion["tree_size"]].root_sha256
                        == inclusion["root_sha256"]
                    ),
                    **inclusion,
                }

        active_job = next(
            (job for job in qualifying if str(job.state) in _ACTIVE_CHECKPOINT_STATES),
            None,
        )
        failed_job = next(
            (job for job in qualifying if str(job.state) == str(BlockchainAnchorJobState.FAILED)),
            None,
        )
        if confirmed_anchor is not None:
            public_status = "CONFIRMED"
            selected_job = confirmed_anchor
        elif invalid_confirmations:
            public_status = "VERIFICATION_FAILED"
            selected_job = None
        elif not ledger_status.get("checkpoint_writes_enabled"):
            public_status = "DISABLED"
            selected_job = active_job or failed_job
        elif active_job is not None:
            public_status = "PENDING"
            selected_job = active_job
        elif failed_job is not None:
            public_status = "FAILED"
            selected_job = failed_job
        else:
            public_status = "PENDING"
            selected_job = None

        checkpoint = (
            checkpoints_by_size.get(_checkpoint_tree_size(confirmed_anchor) or 0)
            if confirmed_anchor is not None
            else None
        )
        public_receipt = (
            checkpoint.external_commitment
            if checkpoint is not None and checkpoint.external_commitment is not None
            else (
                _portable_receipt(dict((confirmed_anchor.receipt or {}).get("receipt") or {}))
                if confirmed_anchor is not None
                else None
            )
        )
        items.append(
            {
                "event": event.payload,
                "payload_digest_sha256": event.payload_digest_sha256,
                "signature": {
                    "alg": event.signature_alg,
                    "kid": event.signature_kid,
                    "signature_b64": event.signature_b64,
                    "cose_sign1_b64": event.cose_sign1_b64,
                },
                "transparency": transparency,
                "public_chain": {
                    "status": public_status,
                    "chain_writes_enabled": ledger_status.get("chain_writes_enabled", False),
                    "checkpoint_writes_enabled": ledger_status.get(
                        "checkpoint_writes_enabled", False
                    ),
                    "job_id": selected_job.id if selected_job is not None else None,
                    "job_state": str(selected_job.state) if selected_job is not None else None,
                    "binding_verified": confirmed_checks is not None,
                    "binding_checks": confirmed_checks,
                    "portable_receipt_persisted": bool(
                        checkpoint is not None and checkpoint.external_commitment is not None
                    ),
                    "invalid_confirmations": invalid_confirmations,
                },
                # Kept for v1 consumers; populated only after all independent
                # leaf -> root -> queued hash -> on-chain receipt checks pass.
                "public_chain_anchor": public_receipt,
            }
        )
    return {
        "schema": "creatorproof.subject_integrity.v1",
        "subject_type": subject_type,
        "subject_id": subject_id,
        "events": items,
        "trust_note": (
            "Signatures prove issuer integrity; an EAS checkpoint proves publication time. "
            "Neither establishes legal ownership or that an assertion is true."
        ),
    }


@router.get("/preflight")
def proof_preflight(
    auth: Annotated[AuthContext, Depends(require_scope(CredentialScope.ADMIN))],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    """Check chain reachability, signer address and balance before a live demo."""
    del auth
    anchor = container.proof_anchor
    if not hasattr(anchor, "preflight"):
        return {
            "ready": False,
            "reason": "PROOF_PROVIDER_IS_NOT_A_CHAIN_ANCHOR",
            "provider": anchor.name,
        }
    return {"provider": anchor.name, **anchor.preflight()}


@router.get("/attestations/{attestation_uid}")
def verify_attestation(
    attestation_uid: str,
    auth: Annotated[
        AuthContext,
        Depends(require_any_scope(*_PROOF_READ_SCOPES)),
    ],
    container: Annotated[Container, Depends(get_container)],
    db: Annotated[Session, Depends(get_db)],
    expected_packet_hash_sha256: Annotated[str | None, Query()] = None,
) -> dict:
    """Re-check an attestation UID against the live EAS contract."""
    anchor = container.proof_anchor
    if not hasattr(anchor, "verify"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "NOT_A_CHAIN_ANCHOR",
                "message": "This deployment is not configured with an on-chain proof provider.",
                "provider": anchor.name,
            },
        )
    ledger_status = container.blockchain.status()
    candidate_jobs = db.scalars(
        select(BlockchainAnchorJob).where(
            BlockchainAnchorJob.state == BlockchainAnchorJobState.CONFIRMED,
            BlockchainAnchorJob.deployment_id == ledger_status["deployment_id"],
        )
    ).all()
    stored_job = next(
        (
            job
            for job in candidate_jobs
            if (
                (job.tenant_id is None or job.tenant_id == auth.tenant_id)
                and str(
                    ((job.receipt or {}).get("receipt") or {}).get("attestation_uid", "")
                ).lower()
                == attestation_uid.lower()
            )
        ),
        None,
    )
    stored_receipt = ((stored_job.receipt or {}).get("receipt") or {}) if stored_job else {}
    caller_expected = (
        _normalize_sha256(expected_packet_hash_sha256)
        if expected_packet_hash_sha256 is not None
        else None
    )
    stored_expected = stored_job.commitment_hash_sha256.lower() if stored_job else None
    if (
        caller_expected is not None
        and stored_expected is not None
        and caller_expected != stored_expected
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "EXPECTED_COMMITMENT_DISAGREES_WITH_DURABLE_JOB",
                "expected_packet_hash_sha256": caller_expected,
                "stored_commitment_hash_sha256": stored_expected,
            },
        )
    effective_expected = stored_expected or caller_expected
    if effective_expected is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EXPECTED_COMMITMENT_REQUIRED",
                "message": (
                    "No current-deployment job binds this UID. Supply an independently "
                    "obtained expected_packet_hash_sha256."
                ),
            },
        )

    commitment_type = stored_job.commitment_type if stored_job else "EVIDENCE_PACKET"
    checkpoint_commitment = commitment_type == "TRANSPARENCY_CHECKPOINT"
    expected_metadata = {
        "commitment_type": commitment_type,
        # Trust roots come from the active deployment configuration, never from
        # mutable receipt JSON supplied by a prior worker.
        "chain_id": container.settings.eas_chain_id,
        "contract_address": container.settings.eas_contract_address,
        "schema_uid": (
            container.settings.eas_checkpoint_schema_uid
            if checkpoint_commitment
            else container.settings.eas_schema_uid
        ),
        "attester_address": container.settings.eas_required_attester_address,
        "recipient": container.settings.eas_recipient,
    }
    result = anchor.verify(
        attestation_uid=attestation_uid,
        expected_commitment_hash=effective_expected,
        expected_metadata=expected_metadata,
    )
    checks = result.get("checks") or {}
    binding_matches = bool(
        result.get("attestation_valid") and checks.get("commitment_matches_expected") is True
    )
    finality_policy = str(
        stored_receipt.get("finality_policy") or container.settings.eas_finality_policy
    )
    return {
        "provider": anchor.name,
        **result,
        "binding_matches": binding_matches,
        "expected_packet_hash_sha256": effective_expected,
        "binding_source": "CURRENT_DEPLOYMENT_JOB" if stored_job else "CALLER_PIN",
        "actual_packet_hash_sha256": result.get("packet_hash_sha256")
        or result.get("commitment_hash_sha256"),
        "confirmed": bool(
            stored_job
            and stored_job.state == BlockchainAnchorJobState.CONFIRMED
            and _receipt_anchor_conditions_met(stored_receipt)
            and result.get("attestation_valid") is True
            and binding_matches
        ),
        "anchor_conditions_met": _receipt_anchor_conditions_met(stored_receipt),
        "finality_policy": finality_policy,
        "confirmation_depth_reached": stored_receipt.get(
            "confirmation_depth_reached", stored_receipt.get("finality_reached")
        ),
        "safe_block_verified": stored_receipt.get("safe_block_verified"),
        "finalized_block_verified": stored_receipt.get("finalized_block_verified"),
        "confirmation_basis": "CANONICAL_RECEIPT_AND_" + finality_policy.upper(),
        "protocol_finality_state": (
            "FINALIZED_BLOCK_VERIFIED"
            if stored_receipt.get("finalized_block_verified") is True
            else (
                "SAFE_BLOCK_VERIFIED"
                if stored_receipt.get("safe_block_verified") is True
                else "NOT_VERIFIED"
            )
        ),
        "finalized": bool(
            stored_receipt.get("finalized_block_verified") is True
            and result.get("attestation_valid") is True
            and binding_matches
        ),
        "transaction_hash": stored_receipt.get("transaction_hash"),
        "block_number": stored_receipt.get("block_number"),
        "block_hash": stored_receipt.get("block_hash"),
        "confirmations": stored_receipt.get("confirmations"),
        "required_confirmations": stored_receipt.get("required_confirmations"),
    }


@router.get("/transparency/checkpoint")
def latest_checkpoint(
    auth: Annotated[AuthContext, Depends(require_any_scope(*_PROOF_READ_SCOPES))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> dict:
    del auth
    checkpoint = container.transparency.latest_checkpoint(db)
    return {
        "log_id": container.transparency.log_id,
        "checkpoint": checkpoint,
        "scope": "LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN",
    }


@router.get("/transparency/consistency", response_model=TransparencyConsistencyRead)
def transparency_consistency(
    auth: Annotated[AuthContext, Depends(require_any_scope(*_PROOF_READ_SCOPES))],
    db: Annotated[Session, Depends(get_db)],
    container: Annotated[Container, Depends(get_container)],
) -> TransparencyConsistencyRead:
    """Recompute every signed checkpoint root to detect an equivocating log."""
    del auth
    return TransparencyConsistencyRead(**container.transparency.check_consistency(db))


@router.get("/trust-bundle")
def trust_bundle(
    db: Annotated[Session, Depends(get_db)],
    auth: Annotated[AuthContext, Depends(require_any_scope(*_PROOF_READ_SCOPES))],
    include_retired: Annotated[bool, Query()] = True,
) -> dict:
    """Public keys needed to verify statements, including rotated historical keys."""
    del auth
    query = select(SigningKey).order_by(SigningKey.created_at)
    keys = list(db.scalars(query).all())
    return {
        "schema": "creatorproof.trust_bundle.v1",
        "keys": [
            {
                "kid": key.kid,
                "algorithm": key.algorithm,
                "public_key_hex": key.public_key_hex,
                "active": key.active,
                "retired_at": key.retired_at.isoformat() if key.retired_at else None,
            }
            for key in keys
            if include_retired or key.active
        ],
        "note": (
            "Retired keys are retained so statements signed before a rotation remain verifiable."
        ),
    }
