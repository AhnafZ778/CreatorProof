"""Fail-closed competition acceptance check for CreatorProof blockchain use.

This command is deliberately stricter than a configuration check.  It requires
the active deployment to be live, then independently reconciles at least one
direct evidence-packet attestation and one batched transparency-checkpoint
attestation from the current deployment.  It never prints RPC credentials,
private keys, signed raw transactions, media, or tenant data.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from app.container import build_container
from app.core.config import Settings
from app.domain.enums import AnchorStatus
from app.domain.platform import BlockchainAnchorJobState, BlockchainCommitmentType
from app.models import BlockchainAnchorJob
from app.services.blockchain import deployment_manifest


def _public_receipt(receipt: dict) -> dict:
    explorer = receipt.get("explorer_urls") or receipt.get("explorer") or {}
    return {
        "transaction_hash": receipt.get("transaction_hash"),
        "attestation_uid": receipt.get("attestation_uid"),
        "block_number": receipt.get("block_number"),
        "block_hash": receipt.get("block_hash"),
        "chain_id": receipt.get("chain_id"),
        "contract_address": receipt.get("contract_address"),
        "schema_uid": receipt.get("schema_uid"),
        "attester_address": receipt.get("attester_address"),
        "anchor_conditions_met": receipt.get("anchor_conditions_met"),
        "safe_block_verified": receipt.get("safe_block_verified"),
        "finalized_block_verified": receipt.get("finalized_block_verified"),
        "explorer_urls": explorer,
    }


def run_acceptance(settings: Settings) -> dict:
    container = build_container(settings)
    failures: list[str] = []
    checks: dict = {}

    checks["explicit_eas_mode"] = settings.proof_anchor_mode == "eas"
    checks["chain_required"] = settings.proof_require_chain is True
    checks["statement_signing_key_source"] = container.signer.status().get("key_source")
    # `CONFIGURED` is the signer's own vocabulary for an operator-supplied key; the
    # alternative, `DERIVED_DEVELOPMENT_KEY`, dies with the process.
    checks["operator_managed_statement_key"] = (
        container.signer.status().get("key_source") == "CONFIGURED"
    )
    for name in ("explicit_eas_mode", "chain_required", "operator_managed_statement_key"):
        if not checks[name]:
            failures.append(name.upper())

    anchor = container.proof_anchor
    if not hasattr(anchor, "preflight") or not hasattr(anchor, "reconcile"):
        failures.append("EAS_PROVIDER_NOT_ACTIVE")
        preflight = {"ready": False, "reason": "EAS_PROVIDER_NOT_ACTIVE"}
    else:
        preflight = anchor.preflight()
        if not preflight.get("ready"):
            failures.append(str(preflight.get("reason") or "EAS_PREFLIGHT_FAILED"))
    checks["preflight"] = preflight

    try:
        ledger = container.blockchain.status()
    except Exception as exc:
        ledger = {
            "deployment_id": getattr(container.blockchain, "_deployment_id", None),
            "states": {},
        }
        failures.append(f"BLOCKCHAIN_LEDGER_UNAVAILABLE:{type(exc).__name__}")
    checks["deployment_id"] = ledger.get("deployment_id")
    checks["deployment_manifest"] = deployment_manifest(settings)
    checks["current_deployment_job_states"] = ledger.get("states") or {}

    required_commitments = [
        BlockchainCommitmentType.EVIDENCE_PACKET,
        BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT,
    ]
    # A deployment that advertises multi-party attestation must be able to show a
    # real counterparty commitment, not just the capability to accept one.
    if ledger.get("counterparty_writes_enabled"):
        required_commitments.append(BlockchainCommitmentType.COUNTERPARTY_ATTESTATION)
    checks["required_commitment_types"] = [str(item) for item in required_commitments]

    verified: dict[str, dict] = {}
    if not failures:
        db = container.database.system_session()
        try:
            for commitment_type in required_commitments:
                job = db.scalar(
                    select(BlockchainAnchorJob)
                    .where(
                        BlockchainAnchorJob.deployment_id == ledger["deployment_id"],
                        BlockchainAnchorJob.commitment_type == str(commitment_type),
                        BlockchainAnchorJob.state == BlockchainAnchorJobState.CONFIRMED,
                    )
                    .order_by(BlockchainAnchorJob.confirmed_at.desc())
                    .limit(1)
                )
                if job is None or not job.transaction_hash:
                    failures.append(f"NO_CONFIRMED_{commitment_type}_TRANSACTION")
                    continue
                expected_schema = {
                    BlockchainCommitmentType.TRANSPARENCY_CHECKPOINT: (
                        settings.eas_checkpoint_schema_uid
                    ),
                    BlockchainCommitmentType.COUNTERPARTY_ATTESTATION: (
                        settings.eas_coattestation_schema_uid
                    ),
                }.get(commitment_type, settings.eas_schema_uid)
                expected_metadata = {
                    "commitment_type": str(commitment_type),
                    "chain_id": settings.eas_chain_id,
                    "contract_address": settings.eas_contract_address,
                    "schema_uid": expected_schema,
                    "attester_address": settings.eas_required_attester_address,
                    "recipient": settings.eas_recipient,
                }
                if commitment_type == BlockchainCommitmentType.COUNTERPARTY_ATTESTATION:
                    # Without the reference the co-attestation is only a lone hash;
                    # the binding to the platform attestation is the whole point.
                    expected_metadata["ref_uid"] = (job.context or {}).get("ref_uid")
                live = anchor.reconcile(
                    transaction_hash=job.transaction_hash,
                    expected_commitment_hash=job.commitment_hash_sha256,
                    expected_metadata=expected_metadata,
                )
                accepted = live.status == AnchorStatus.ANCHORED
                if not accepted:
                    failures.append(f"LIVE_{commitment_type}_RECONCILIATION_FAILED")
                verified[str(commitment_type)] = {
                    "accepted": accepted,
                    "status": str(live.status),
                    "commitment_hash_sha256": job.commitment_hash_sha256,
                    "receipt": _public_receipt(live.receipt),
                }
        finally:
            db.close()
    checks["live_reconciled_examples"] = verified
    return {
        "schema": "creatorproof.blockchain_competition_acceptance.v1",
        "accepted": not failures,
        "failures": failures,
        "checks": checks,
        "claim_boundary": (
            "Acceptance proves public publication and binding of hashes. It does not prove "
            "authorship, ownership, non-infringement, or detector accuracy."
        ),
    }


def main() -> int:
    try:
        result = run_acceptance(Settings())
    except Exception as exc:
        result = {
            "schema": "creatorproof.blockchain_competition_acceptance.v1",
            "accepted": False,
            "failures": [f"ACCEPTANCE_CHECK_FAILED:{type(exc).__name__}"],
        }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
