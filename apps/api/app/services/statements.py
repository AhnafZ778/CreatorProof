"""Evidence Statement v2.

The statement is derived from Agent A's Evidence Packet without changing any
lane semantics. It adds the identities, canonicalization and signature needed to
verify a result offline, plus an append-only lineage so a correction, dispute,
supersession or revocation never mutates history.

The proof object is deliberately excluded from the signed payload: a chain
receipt is supplemental and must never be able to change evidence truth.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.platform import StatementStatus, StatementType
from app.services.canonical import canonicalize
from app.services.signing import verify_statement_signature

logger = logging.getLogger("creatorproof.statements")

STATEMENT_SCHEMA_VERSION = "creatorproof.statement.v2"
ISSUER = "creatorproof"

_STATUS_BY_STATEMENT_TYPE = {
    StatementType.CORRECTION: StatementStatus.SUPERSEDED,
    StatementType.DISPUTE: StatementStatus.DISPUTED,
    StatementType.SUPERSESSION: StatementStatus.SUPERSEDED,
    StatementType.REVOCATION: StatementStatus.REVOKED,
}


def _linear_statement_lineage(statement, rows: list) -> tuple[list, StatementStatus]:
    """Return the exact successor chain and derive status from signed event types.

    Mutable ``status`` columns are useful query projections, but they are not a
    trust source.  Verification packages must therefore derive current status
    exclusively from the signed, digest-linked lineage.
    """
    by_predecessor: dict[str, object] = {}
    unrelated: list[str] = []
    for row in rows:
        if row.id == statement.id:
            continue
        predecessor = row.previous_statement_id
        if not predecessor:
            unrelated.append(row.id)
            continue
        if predecessor in by_predecessor:
            raise ValueError(f"Statement lineage branches at {predecessor}")
        by_predecessor[predecessor] = row

    lineage = [statement]
    derived_status = StatementStatus.ACTIVE
    while lineage[-1].id in by_predecessor:
        successor = by_predecessor.pop(lineage[-1].id)
        try:
            event_type = StatementType(successor.statement_type)
        except ValueError as exc:
            raise ValueError(
                f"Unsupported statement type in lineage: {successor.statement_type}"
            ) from exc
        if event_type not in _STATUS_BY_STATEMENT_TYPE:
            raise ValueError(f"Invalid successor statement type: {event_type}")
        expected_digest = lineage[-1].payload_digest_sha256
        if successor.payload.get("previous_payload_digest_sha256") != expected_digest:
            raise ValueError(f"Statement {successor.id} does not bind its predecessor digest")
        lineage.append(successor)
        derived_status = _STATUS_BY_STATEMENT_TYPE[event_type]

    if by_predecessor or unrelated:
        raise ValueError("Scan contains a disconnected statement lineage")
    return lineage, derived_status


def _scope_section(packet: dict) -> dict:
    scope = packet.get("scope") or {}
    return {
        "snapshot_id": scope.get("snapshot_id"),
        "snapshot_digest_sha256": scope.get("snapshot_digest_sha256"),
        "catalog_id": scope.get("catalog_id"),
        "catalog_version": scope.get("catalog_version"),
        "coverage_status": scope.get("coverage_status"),
        "coverage_reason_codes": list(scope.get("coverage_reason_codes") or []),
        "complete_for_declared_catalog": bool(scope.get("complete_for_declared_catalog", False)),
        "eligible_reference_count": scope.get("eligible_reference_count"),
        "nominated_candidate_count": scope.get("nominated_candidate_count"),
        "verified_candidate_count": scope.get("verified_candidate_count"),
        "omitted_candidate_count": scope.get("omitted_candidate_count"),
        "failed_candidate_count": scope.get("failed_candidate_count"),
        "capabilities": scope.get("capabilities") or {},
    }


def _findings_section(packet: dict) -> dict:
    """Keep the five lanes separate exactly as Agent A reports them."""
    decision = packet.get("decision") or {}
    style = packet.get("style_analysis") or {}
    origin = packet.get("synthetic_origin") or {}
    provenance = packet.get("provenance") or {}
    matches = packet.get("matches") or []
    return {
        "copy": {
            "match_status": decision.get("match_status"),
            "top_match_work_id": (matches[0] or {}).get("work_id") if matches else None,
            "verified_candidate_count": (packet.get("scope") or {}).get("verified_candidate_count"),
            "ranked_matches": [
                {
                    "work_id": item.get("work_id"),
                    "retrieval_rank": item.get("retrieval_rank"),
                    "verification_rank": item.get("verification_rank"),
                    "verification_state": item.get("verification_state"),
                    "copy_evidence_score": item.get("copy_evidence_score"),
                }
                for item in matches
            ],
        },
        "ai_origin": {
            "classification": origin.get("classification"),
            "policy_mode": origin.get("policy_mode"),
            "execution_state": origin.get("execution_state"),
            "abstained": origin.get("abstained"),
        },
        "creator_profile_resemblance": {
            "customer_facing_lane": style.get("customer_facing_lane"),
            "classification": (style.get("decision") or {}).get("classification"),
            "evidence_tier": (style.get("decision") or {}).get("evidence_tier"),
            "review_recommended": (style.get("decision") or {}).get("review_recommended"),
            "advisory_only": True,
        },
        "provenance": {
            "provider": provenance.get("provider"),
            "status": provenance.get("status"),
            "reason_codes": list(provenance.get("reason_codes") or []),
        },
        "rights": {
            "rights_path": decision.get("rights_path"),
            "policy_inputs": decision.get("policy_inputs") or {},
        },
    }


def build_statement_payload(
    *,
    scan,
    packet: dict,
    statement_id: str,
    statement_type: StatementType = StatementType.RESULT,
    previous_statement_id: str | None = None,
    policy_version_id: str | None = None,
    catalog_version_id: str | None = None,
    stage_digests: dict | None = None,
    extra: dict | None = None,
) -> dict:
    decision = packet.get("decision") or {}
    payload = {
        "schema": STATEMENT_SCHEMA_VERSION,
        "statement_id": statement_id,
        "statement_type": str(statement_type),
        "issuer": ISSUER,
        "tenant_id": scan.tenant_id,
        "created_at": datetime.now(UTC).isoformat(),
        "scan_id": scan.id,
        "previous_statement_id": previous_statement_id,
        "candidate": {
            "sha256": scan.candidate_sha256,
            "phash": scan.candidate_phash,
            "request_digest": scan.request_digest,
        },
        "input_binding": {
            "catalog_id": scan.catalog_id,
            "catalog_version_id": catalog_version_id,
            "intended_use": scan.intended_use,
            "policy_version_id": policy_version_id,
        },
        "scope": _scope_section(packet),
        "models": packet.get("models") or {},
        "stage_digests": stage_digests or {},
        "findings": _findings_section(packet),
        "policy": {
            "policy_version": decision.get("policy_version"),
            "policy_version_id": policy_version_id,
            "policy_action": decision.get("policy_action"),
            "reason_codes": list(decision.get("reason_codes") or []),
            "explanation_trace": (
                decision.get("policy_trace") or decision.get("policy_inputs") or {}
            ),
        },
        "packet_commitment": {
            "packet_hash_sha256": (packet.get("proof") or {}).get("packet_hash_sha256"),
            "commitment_scope": (packet.get("proof") or {}).get("commitment_scope"),
        },
        "limitations": list(packet.get("limitations") or []),
        "verification_notes": [
            "This statement is canonicalized with RFC 8785 JCS before hashing and signing.",
            "The proof object is intentionally outside the signed payload; a chain receipt "
            "commits the referenced evidence-packet hash, not this statement or the truth "
            "of its evidence claims.",
            "Coverage is source-scoped. No-match refers only to the declared catalog.",
        ],
    }
    if extra:
        payload.update(extra)
    return payload


def issue_statement(
    db: Session,
    *,
    signer,
    transparency,
    blockchain=None,
    scan,
    packet: dict,
    statement_type: StatementType = StatementType.RESULT,
    previous_statement_id: str | None = None,
    stage_digests: dict | None = None,
) -> dict:
    """Persist a signed statement and record it in the transparency log."""
    from app.models import EvidenceStatement, new_id

    statement_id = new_id("stm")
    payload = build_statement_payload(
        scan=scan,
        packet=packet,
        statement_id=statement_id,
        statement_type=statement_type,
        previous_statement_id=previous_statement_id,
        policy_version_id=scan.policy_version_id,
        catalog_version_id=scan.catalog_version_id,
        stage_digests=stage_digests,
    )
    signed = signer.sign(payload)
    row = EvidenceStatement(
        id=statement_id,
        tenant_id=scan.tenant_id,
        scan_id=scan.id,
        statement_type=str(statement_type),
        schema_version=STATEMENT_SCHEMA_VERSION,
        payload=payload,
        payload_digest_sha256=signed["payload_digest_sha256"],
        signature_kid=signed["signature_kid"],
        signature_alg=signed["signature_alg"],
        signature_b64=signed["signature_b64"],
        cose_sign1_b64=signed["cose_sign1_b64"],
        previous_statement_id=previous_statement_id,
        status=StatementStatus.ACTIVE,
    )
    db.add(row)
    db.commit()

    receipt = None
    try:
        receipt = transparency.append(
            db,
            packet_hash=signed["payload_digest_sha256"],
            statement_id=statement_id,
        )
    except Exception:
        # Transparency inclusion is supplemental. A log failure is reported, never
        # allowed to invalidate a committed evidence statement.
        logger.exception("transparency_append_failed statement_id=%s", statement_id)
    if receipt and blockchain is not None:
        blockchain.enqueue_checkpoint(receipt)

    return {
        "statement_id": statement_id,
        "schema": STATEMENT_SCHEMA_VERSION,
        "statement_type": str(statement_type),
        "payload_digest_sha256": signed["payload_digest_sha256"],
        "signature_alg": signed["signature_alg"],
        "signature_kid": signed["signature_kid"],
        "signature_b64": signed["signature_b64"],
        "key_source": signed["key_source"],
        "transparency": receipt,
    }


def issue_status_statement(
    db: Session,
    *,
    signer,
    transparency,
    blockchain=None,
    scan,
    previous: object,
    statement_type: StatementType,
    reason: str,
    actor_label: str,
) -> dict:
    """Append a correction/dispute/supersession/revocation without mutating history."""
    from app.models import EvidenceStatement, new_id

    if previous.tenant_id != scan.tenant_id or previous.scan_id != scan.id:
        raise ValueError("Previous statement does not belong to this scan")
    if StatementStatus(previous.status) != StatementStatus.ACTIVE:
        raise ValueError(
            f"Statement {previous.id} is already {previous.status}; append to the active tip"
        )
    child_exists = db.scalar(
        select(EvidenceStatement.id)
        .where(EvidenceStatement.previous_statement_id == previous.id)
        .limit(1)
    )
    if child_exists is not None:
        raise ValueError("Statement lineage already has a successor for this statement")

    statement_id = new_id("stm")
    payload = {
        "schema": STATEMENT_SCHEMA_VERSION,
        "statement_id": statement_id,
        "statement_type": str(statement_type),
        "issuer": ISSUER,
        "tenant_id": scan.tenant_id,
        "scan_id": scan.id,
        "created_at": datetime.now(UTC).isoformat(),
        "previous_statement_id": previous.id,
        "previous_payload_digest_sha256": previous.payload_digest_sha256,
        "reason": reason,
        "actor_label": actor_label,
        "verification_notes": [
            "The referenced statement remains valid and verifiable; this record changes "
            "its current status only.",
        ],
    }
    signed = signer.sign(payload)
    db.add(
        EvidenceStatement(
            id=statement_id,
            tenant_id=scan.tenant_id,
            scan_id=scan.id,
            statement_type=str(statement_type),
            schema_version=STATEMENT_SCHEMA_VERSION,
            payload=payload,
            payload_digest_sha256=signed["payload_digest_sha256"],
            signature_kid=signed["signature_kid"],
            signature_alg=signed["signature_alg"],
            signature_b64=signed["signature_b64"],
            cose_sign1_b64=signed["cose_sign1_b64"],
            previous_statement_id=previous.id,
            status=StatementStatus.ACTIVE,
        )
    )
    new_status = {
        StatementType.DISPUTE: StatementStatus.DISPUTED,
        StatementType.SUPERSESSION: StatementStatus.SUPERSEDED,
        StatementType.CORRECTION: StatementStatus.SUPERSEDED,
        StatementType.REVOCATION: StatementStatus.REVOKED,
    }.get(statement_type)
    if new_status is not None:
        # Status lives on a mutable column of an otherwise immutable row, so the
        # ORM guard is bypassed with a targeted UPDATE that preserves the payload.
        db.query(EvidenceStatement).filter(EvidenceStatement.id == previous.id).update(
            {"status": str(new_status)}, synchronize_session=False
        )
    db.commit()

    receipt = None
    try:
        receipt = transparency.append(
            db, packet_hash=signed["payload_digest_sha256"], statement_id=statement_id
        )
    except Exception:
        logger.exception("transparency_append_failed statement_id=%s", statement_id)
    if receipt and blockchain is not None:
        blockchain.enqueue_checkpoint(receipt)

    return {
        "statement_id": statement_id,
        "statement_type": str(statement_type),
        "previous_statement_id": previous.id,
        "payload_digest_sha256": signed["payload_digest_sha256"],
        "transparency": receipt,
    }


def latest_statement(db: Session, *, tenant_id: str, scan_id: str):
    from app.models import EvidenceStatement

    return db.scalar(
        select(EvidenceStatement)
        .where(
            EvidenceStatement.tenant_id == tenant_id,
            EvidenceStatement.scan_id == scan_id,
            EvidenceStatement.statement_type == str(StatementType.RESULT),
        )
        .order_by(EvidenceStatement.created_at.desc())
        .limit(1)
    )


def active_statement(db: Session, *, tenant_id: str, scan_id: str):
    """Return the one current lineage tip, regardless of its statement type."""
    from app.models import EvidenceStatement

    return db.scalar(
        select(EvidenceStatement)
        .where(
            EvidenceStatement.tenant_id == tenant_id,
            EvidenceStatement.scan_id == scan_id,
            EvidenceStatement.status == str(StatementStatus.ACTIVE),
        )
        .order_by(EvidenceStatement.created_at.desc(), EvidenceStatement.id.desc())
        .limit(1)
    )


def build_verification_package(
    db: Session,
    statement,
    *,
    signer,
    transparency,
    packet: dict | None = None,
    settings=None,
) -> dict:
    """Everything an auditor needs to verify a statement without calling the API."""
    checkpoint = transparency.latest_checkpoint(db)
    from app.models import EvidenceStatement, TransparencyLeaf
    from app.services.blockchain import deployment_id, deployment_manifest, issuer_key_fingerprint
    from app.services.evidence import canonical_packet_bytes

    leaf = db.scalar(
        select(TransparencyLeaf).where(TransparencyLeaf.statement_id == statement.id).limit(1)
    )
    packet = packet or {}
    evidence_packet_without_proof = {key: value for key, value in packet.items() if key != "proof"}
    canonical_packet = canonical_packet_bytes(evidence_packet_without_proof)
    recomputed_packet_hash = hashlib.sha256(canonical_packet).hexdigest()
    proof = packet.get("proof") or {}
    receipt = proof.get("receipt") or {}
    explorer_urls = receipt.get("explorer_urls") or receipt.get("explorer") or {}
    if isinstance(explorer_urls, str):
        explorer_urls = {"transaction": explorer_urls}
    proof_binding = {
        "packet_hash_sha256": proof.get("packet_hash_sha256") or recomputed_packet_hash,
        "proof_kind": receipt.get("proof_kind") or "EVIDENCE_PACKET",
        "anchor_scope": receipt.get("anchor_scope"),
        "chain_id": receipt.get("chain_id"),
        "contract_address": receipt.get("contract_address"),
        "schema_uid": receipt.get("schema_uid"),
        "attestation_uid": receipt.get("attestation_uid"),
        "attester_address": receipt.get("attester_address") or receipt.get("attester"),
        "recipient_address": receipt.get("recipient_address") or receipt.get("recipient"),
        "transaction_hash": receipt.get("transaction_hash") or receipt.get("tx_hash"),
        "block_number": receipt.get("block_number"),
        "block_hash": receipt.get("block_hash"),
        "confirmations": receipt.get("confirmations"),
        "required_confirmations": receipt.get("required_confirmations"),
        "finality_policy": receipt.get("finality_policy"),
        "anchor_conditions_met": receipt.get("anchor_conditions_met"),
        # `finality_reached` in legacy v3 receipts meant only that a configured
        # confirmation count was reached.  It must never be upgraded into a
        # protocol-finality claim in a newly signed package.
        "finalized": receipt.get("finalized") is True,
        "transaction_status": receipt.get("transaction_status"),
        "attestation_valid": receipt.get("attestation_valid"),
        "canonical_receipt": receipt.get("canonical_receipt"),
        "confirmation_depth_reached": receipt.get(
            "confirmation_depth_reached", receipt.get("finality_reached")
        ),
        "safe_block_verified": receipt.get("safe_block_verified"),
        "finalized_block_verified": receipt.get("finalized_block_verified"),
        "explorer_urls": explorer_urls,
    }
    binding_signed = signer.sign(proof_binding)
    lineage_rows = list(
        db.scalars(
            select(EvidenceStatement)
            .where(
                EvidenceStatement.tenant_id == statement.tenant_id,
                EvidenceStatement.scan_id == statement.scan_id,
            )
            .order_by(EvidenceStatement.created_at, EvidenceStatement.id)
        ).all()
    )
    lineage, derived_status = _linear_statement_lineage(statement, lineage_rows)
    checkpoint_body = (
        {
            "log_id": transparency.log_id,
            "tree_size": checkpoint["tree_size"],
            "root_sha256": checkpoint["root_sha256"],
        }
        if checkpoint
        else None
    )
    lineage_binding = {
        "schema": "creatorproof.statement_lineage_binding.v1",
        "scan_id": statement.scan_id,
        "root_statement_id": statement.id,
        "current_status": str(derived_status),
        "statement_ids": [row.id for row in lineage],
        "payload_digests_sha256": [row.payload_digest_sha256 for row in lineage],
        "checkpoint": checkpoint_body,
    }
    lineage_binding_signed = signer.sign(lineage_binding)
    deployment_fingerprint = deployment_id(settings) if settings is not None else None
    public_deployment_manifest = deployment_manifest(settings) if settings is not None else None
    signed_tree_size = int(checkpoint["tree_size"]) if checkpoint else None
    checkpoint_covers_leaf = bool(
        leaf is not None and signed_tree_size is not None and leaf.leaf_index < signed_tree_size
    )
    inclusion = (
        transparency.inclusion_proof(
            db,
            leaf_index=leaf.leaf_index,
            tree_size=signed_tree_size,
        )
        if checkpoint_covers_leaf
        else None
    )
    package = {
        "schema": "creatorproof.verification_package.v1",
        "statement": statement.payload,
        "signature": {
            "alg": statement.signature_alg,
            "kid": statement.signature_kid,
            "signature_b64": statement.signature_b64,
            "cose_sign1_b64": statement.cose_sign1_b64,
        },
        "payload_digest_sha256": statement.payload_digest_sha256,
        # Informational compatibility field. Verifiers must still derive this
        # value from the signed lineage and its signed binding.
        "status": str(derived_status),
        "statement_lineage": [
            {
                "statement": row.payload,
                "payload_digest_sha256": row.payload_digest_sha256,
                "statement_type": row.statement_type,
                "previous_statement_id": row.previous_statement_id,
                "status": row.status,
                "signature": {
                    "alg": row.signature_alg,
                    "kid": row.signature_kid,
                    "signature_b64": row.signature_b64,
                    "cose_sign1_b64": row.cose_sign1_b64,
                },
            }
            for row in lineage
        ],
        "statement_lineage_binding": lineage_binding,
        "statement_lineage_binding_signature": {
            "alg": lineage_binding_signed["signature_alg"],
            "kid": lineage_binding_signed["signature_kid"],
            "signature_b64": lineage_binding_signed["signature_b64"],
            "cose_sign1_b64": lineage_binding_signed["cose_sign1_b64"],
            "payload_digest_sha256": lineage_binding_signed["payload_digest_sha256"],
            "canonicalization": "RFC8785_JCS_COSE_SIGN1",
        },
        "evidence_packet_without_proof": evidence_packet_without_proof,
        "evidence_packet_canonical_b64": base64.b64encode(canonical_packet).decode("ascii"),
        "evidence_packet_canonicalization": "CREATORPROOF_SORTED_JSON_ASCII_V1",
        "proof_binding": proof_binding,
        "proof_binding_signature": {
            "alg": binding_signed["signature_alg"],
            "kid": binding_signed["signature_kid"],
            "signature_b64": binding_signed["signature_b64"],
            "cose_sign1_b64": binding_signed["cose_sign1_b64"],
            "payload_digest_sha256": binding_signed["payload_digest_sha256"],
            "canonicalization": "RFC8785_JCS_COSE_SIGN1",
        },
        "deployment": {
            "issuer": ISSUER,
            "issuer_key_fingerprint_sha256": issuer_key_fingerprint(signer),
            "deployment_fingerprint_sha256": deployment_fingerprint,
            "manifest": public_deployment_manifest,
        },
        "trust_bundle": {
            "keys": [
                {
                    "kid": key.kid,
                    "algorithm": key.algorithm,
                    "public_key_hex": key.public_key_hex,
                    "active": key.active,
                }
                for key in _trust_bundle(db)
            ]
        },
        "transparency": {
            "log_id": transparency.log_id,
            "leaf_index": leaf.leaf_index if leaf else None,
            "leaf_hash_sha256": leaf.leaf_hash_sha256 if leaf else None,
            "packet_hash_sha256": leaf.packet_hash_sha256 if leaf else None,
            "latest_checkpoint": checkpoint,
            "scope": "LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN",
            **(inclusion or {}),
        },
        "instructions": [
            "Canonicalize `statement` with RFC 8785 JCS and SHA-256 it; the result must "
            "equal payload_digest_sha256.",
            "Verify signature_b64 over the COSE Sig_structure using the matching kid from "
            "trust_bundle.",
            "Run scripts/verify_evidence_statement.py for an automated check.",
            "Hash evidence_packet_canonical_b64 bytes and match proof_binding.packet_hash_sha256.",
            "Verify proof_binding_signature with an externally pinned issuer key.",
            "Verify every statement_lineage signature and the signed lineage binding before "
            "interpreting current_status.",
            "Verify latest_checkpoint.signature_b64 over {log_id, tree_size, root_sha256}; "
            "an inclusion path to an unsigned package-supplied root is not a trust proof.",
            "A package authenticates the issuer declaration only; re-check the attestation "
            "against a trusted RPC to establish current chain state and finality.",
        ],
    }
    return package


def _trust_bundle(db: Session):
    from app.models import SigningKey

    return db.scalars(select(SigningKey).order_by(SigningKey.created_at)).all()


def verify_statement_row(db: Session, statement) -> dict:
    """Verify a stored statement against the persisted trust bundle."""
    from app.models import SigningKey

    if not statement.signature_b64 or not statement.signature_kid:
        return {"valid": False, "reason": "STATEMENT_UNSIGNED"}
    key = db.scalar(select(SigningKey).where(SigningKey.kid == statement.signature_kid))
    if key is None:
        return {"valid": False, "reason": "UNKNOWN_SIGNING_KEY"}
    digest_matches = (
        __import__("hashlib").sha256(canonicalize(statement.payload)).hexdigest()
        == statement.payload_digest_sha256
    )
    signature_valid = verify_statement_signature(
        statement.payload,
        signature_b64=statement.signature_b64,
        public_key_hex=key.public_key_hex,
    )
    return {
        "valid": bool(digest_matches and signature_valid),
        "digest_matches": digest_matches,
        "signature_valid": signature_valid,
        "kid": statement.signature_kid,
        "status": statement.status,
    }
