"""Counterparty co-attestation: a second party commits to a clearance result.

CreatorProof's own attestation proves when an evidence packet existed. It cannot
prove that a brand, agency or marketplace accepted that result, because
CreatorProof controls the key that wrote it. A co-attestation closes that gap:
the counterparty signs, with its own EVM key, a canonical body that names the
packet, the decision and itself. CreatorProof verifies the recovered address
against the network's membership registry and commits only the body hash, bound
to the platform attestation through EAS ``refUID``.

What this proves: this member committed to this decision, about this packet, at
this time. What it does not prove: that the decision is correct, that the member
held authority, or that any rights claim is true.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.domain.platform import (
    CounterpartyAttestationState,
    CounterpartyDecision,
    NetworkMemberRole,
    NetworkMemberStatus,
)
from app.providers.counterparty_signature import CounterpartySignatureUnavailable
from app.services.canonical import CanonicalizationError, canonical_digest

logger = logging.getLogger("creatorproof.coattestation")

CO_ATTESTATION_SCHEMA = "creatorproof.counterparty_attestation.v1"
CO_ATTESTATION_EVENT = "COUNTERPARTY_ATTESTATION_RECORDED"
CO_ATTESTATION_WITHDRAWN_EVENT = "COUNTERPARTY_ATTESTATION_WITHDRAWN"

# Every field is part of the signed commitment. A body with any other shape is
# refused rather than normalized, so a signature can never cover less than the
# verifier later reads back.
BODY_FIELDS = frozenset(
    {
        "schema",
        "chain_id",
        "verifying_contract",
        "deployment_id",
        "scan_id",
        "packet_hash_sha256",
        "platform_attestation_uid",
        "party_org_id",
        "party_role",
        "decision",
        "decision_note_sha256",
        "signer_address",
        "issued_at",
        "nonce",
    }
)

TRUST_NOTE = (
    "A counterparty attestation records that this member signed this decision at this "
    "time. It does not establish that the decision is correct, that the member held "
    "authority, or that any rights claim is true."
)


class CoAttestationError(RuntimeError):
    """A refusal a caller can act on, with a stable machine-readable code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        http_status: int = 409,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_address(value: object) -> str:
    address = str(value or "").strip().lower()
    if not address.startswith("0x") or len(address) != 42:
        raise CoAttestationError(
            "INVALID_EVM_ADDRESS",
            "An EVM address must be 0x followed by 40 hexadecimal characters.",
            http_status=422,
        )
    try:
        bytes.fromhex(address[2:])
    except ValueError as exc:
        raise CoAttestationError(
            "INVALID_EVM_ADDRESS",
            "An EVM address must be 0x followed by 40 hexadecimal characters.",
            http_status=422,
        ) from exc
    return address


def _normalize_sha256(value: object, *, field: str) -> str:
    digest = str(value or "").removeprefix("0x").lower()
    try:
        if len(bytes.fromhex(digest)) != 32:
            raise ValueError
    except ValueError as exc:
        raise CoAttestationError(
            "INVALID_COMMITMENT_HASH",
            f"{field} must be a 32-byte hexadecimal SHA-256 digest.",
            http_status=422,
        ) from exc
    return digest


def scan_commitment(scan) -> tuple[str, str | None]:
    """Return the packet hash a counterparty may commit to, and its chain UID."""
    packet = scan.evidence_packet or {}
    proof = dict(packet.get("proof") or {})
    packet_hash = proof.get("packet_hash_sha256") or proof.get("packet_commitment_sha256")
    if not packet_hash:
        raise CoAttestationError(
            "SCAN_HAS_NO_EVIDENCE_COMMITMENT",
            "This scan has no canonical evidence packet hash to co-attest to yet.",
            http_status=409,
        )
    receipt = dict(proof.get("receipt") or {})
    attestation_uid = receipt.get("attestation_uid")
    return str(packet_hash), (str(attestation_uid) if attestation_uid else None)


def build_body(
    *,
    settings,
    deployment_id: str,
    scan_id: str,
    packet_hash_sha256: str,
    platform_attestation_uid: str | None,
    party_org_id: str,
    party_role: NetworkMemberRole | str,
    decision: CounterpartyDecision | str,
    signer_address: str,
    decision_note_sha256: str | None = None,
    issued_at: datetime | None = None,
    nonce: str | None = None,
) -> dict:
    """Assemble the exact object whose canonical digest the counterparty signs."""
    return {
        "schema": CO_ATTESTATION_SCHEMA,
        "chain_id": int(settings.eas_chain_id) if settings.eas_chain_id else 0,
        "verifying_contract": str(settings.eas_member_registry_address or "").lower(),
        "deployment_id": deployment_id,
        "scan_id": scan_id,
        "packet_hash_sha256": packet_hash_sha256,
        "platform_attestation_uid": (
            str(platform_attestation_uid).lower() if platform_attestation_uid else None
        ),
        "party_org_id": party_org_id,
        "party_role": str(party_role),
        "decision": str(decision),
        "decision_note_sha256": (
            str(decision_note_sha256).lower() if decision_note_sha256 else None
        ),
        "signer_address": str(signer_address).lower(),
        "issued_at": (issued_at or _utcnow()).isoformat(),
        "nonce": nonce or secrets.token_hex(16),
    }


def body_hash(body: dict) -> str:
    try:
        return canonical_digest(body)
    except CanonicalizationError as exc:
        raise CoAttestationError(
            "BODY_NOT_CANONICALIZABLE",
            "The co-attestation body contains values that cannot be canonicalized.",
            http_status=422,
        ) from exc


class CoAttestationService:
    """Collect, verify and durably anchor counterparty commitments."""

    def __init__(self, *, settings, blockchain, verifier, member_registry, signer, transparency):
        self.settings = settings
        self.blockchain = blockchain
        self.verifier = verifier
        self.member_registry = member_registry
        self.signer = signer
        self.transparency = transparency

    # -- capability ------------------------------------------------------

    def capability(self) -> dict:
        """Describe honestly whether this deployment can accept a co-attestation."""
        verifier_status = self.verifier.status()
        registry_status = self.member_registry.status()
        anchoring_ready = bool(self.blockchain is not None and self.blockchain.counterparty_enabled)
        reasons = []
        if not self.settings.blockchain_counterparty_attestation_enabled:
            reasons.append("COUNTERPARTY_ATTESTATION_DISABLED")
        if not verifier_status["available"]:
            reasons.append(verifier_status["reason"] or "SIGNATURE_VERIFIER_UNAVAILABLE")
        if not anchoring_ready:
            reasons.append("COUNTERPARTY_ANCHORING_NOT_CONFIGURED")
        return {
            "enabled": self.settings.blockchain_counterparty_attestation_enabled,
            # Signatures are still collectible and verifiable when anchoring is
            # down; only the public commitment waits.
            "accepting_signatures": bool(
                self.settings.blockchain_counterparty_attestation_enabled
                and verifier_status["available"]
            ),
            "anchoring_ready": anchoring_ready,
            "reasons": reasons,
            "signature": verifier_status,
            "member_registry": registry_status,
            "membership_required": self.settings.counterparty_membership_required,
            "signature_max_age_seconds": self.settings.counterparty_attestation_max_age_seconds,
            "trust_note": TRUST_NOTE,
        }

    def _require_enabled(self) -> None:
        capability = self.capability()
        if not capability["accepting_signatures"]:
            raise CoAttestationError(
                "COUNTERPARTY_ATTESTATION_UNAVAILABLE",
                "This deployment cannot verify counterparty signatures.",
                http_status=409,
                details={"reasons": capability["reasons"]},
            )

    # -- challenge -------------------------------------------------------

    def challenge(
        self,
        db,
        *,
        scan,
        signer_address: str,
        party_org_id: str,
        party_role: str,
        decision: str,
        decision_note_sha256: str | None = None,
    ) -> dict:
        """Return the body, digest and typed data a counterparty must sign."""
        self._require_enabled()
        address = _normalize_address(signer_address)
        role = _coerce_role(party_role)
        resolved_decision = _coerce_decision(decision)
        packet_hash, attestation_uid = scan_commitment(scan)
        membership = self.resolve_membership(db, tenant_id=scan.tenant_id, address=address)
        if not membership["permitted"]:
            raise CoAttestationError(
                "MEMBER_NOT_ACTIVE",
                "This address is not an active member of the attestation network.",
                http_status=403,
                details={"membership": membership},
            )
        body = build_body(
            settings=self.settings,
            deployment_id=self.blockchain.status()["deployment_id"],
            scan_id=scan.id,
            packet_hash_sha256=packet_hash,
            platform_attestation_uid=attestation_uid,
            party_org_id=membership.get("org_id") or party_org_id,
            party_role=role,
            decision=resolved_decision,
            signer_address=address,
            decision_note_sha256=(
                _normalize_sha256(decision_note_sha256, field="decision_note_sha256")
                if decision_note_sha256
                else None
            ),
        )
        digest = body_hash(body)
        issued_at = datetime.fromisoformat(body["issued_at"])
        return {
            "schema": CO_ATTESTATION_SCHEMA,
            "body": body,
            "body_hash_sha256": digest,
            "typed_data": self.verifier.typed_data(digest),
            "signature_algorithm": self.verifier.status()["algorithm"],
            "expires_at": (
                issued_at
                + timedelta(seconds=self.settings.counterparty_attestation_max_age_seconds)
            ).isoformat(),
            "membership": membership,
            "instructions": (
                "Sign the EIP-712 typed data with the member key. Submit the body "
                "unchanged together with the signature; any edit invalidates it."
            ),
            "trust_note": TRUST_NOTE,
        }

    # -- membership ------------------------------------------------------

    def resolve_membership(self, db, *, tenant_id: str, address: str) -> dict:
        """Combine the on-chain registry with local identity metadata.

        The chain decides whether an address may attest. The local row only
        supplies the display name and organization that must not go on chain.
        """
        from app.models import NetworkMember

        address = _normalize_address(address)
        row = db.scalar(
            select(NetworkMember).where(
                NetworkMember.tenant_id == tenant_id,
                NetworkMember.address == address,
            )
        )
        on_chain = self.member_registry.lookup(address)
        local_status = str(row.status) if row is not None else str(NetworkMemberStatus.UNKNOWN)
        if on_chain.get("checked"):
            authority = "ON_CHAIN_REGISTRY"
            permitted = bool(on_chain.get("active"))
            status = str(on_chain.get("status") or NetworkMemberStatus.UNKNOWN)
        elif self.member_registry.configured and self.settings.counterparty_membership_required:
            # A configured registry that cannot be read is an unknown answer, and
            # an unknown answer is not permission.
            authority = "ON_CHAIN_REGISTRY_UNAVAILABLE"
            permitted = False
            status = str(NetworkMemberStatus.UNKNOWN)
        else:
            authority = "LOCAL_DIRECTORY"
            status = local_status
            permitted = (
                status == str(NetworkMemberStatus.ACTIVE)
                or not self.settings.counterparty_membership_required
            )
        return {
            "address": address,
            "permitted": permitted,
            "status": status,
            "authority": authority,
            "membership_required": self.settings.counterparty_membership_required,
            "member_id": row.id if row is not None else None,
            "org_id": row.org_id if row is not None else None,
            "display_name": row.display_name if row is not None else None,
            "role": str(row.role) if row is not None else on_chain.get("role"),
            "local_status": local_status,
            "on_chain": on_chain,
        }

    # -- submission ------------------------------------------------------

    def _validate_body(self, *, body: dict, scan, deployment_id: str) -> dict:
        if not isinstance(body, dict) or set(body.keys()) != BODY_FIELDS:
            raise CoAttestationError(
                "BODY_SHAPE_MISMATCH",
                "The signed body must contain exactly the fields issued by the challenge.",
                http_status=422,
                details={"expected_fields": sorted(BODY_FIELDS)},
            )
        packet_hash, attestation_uid = scan_commitment(scan)
        expected = {
            "schema": CO_ATTESTATION_SCHEMA,
            "chain_id": int(self.settings.eas_chain_id) if self.settings.eas_chain_id else 0,
            "verifying_contract": str(self.settings.eas_member_registry_address or "").lower(),
            "deployment_id": deployment_id,
            "scan_id": scan.id,
            "packet_hash_sha256": packet_hash,
        }
        mismatched = [key for key, value in expected.items() if body.get(key) != value]
        if mismatched:
            raise CoAttestationError(
                "BODY_DOES_NOT_MATCH_DEPLOYMENT",
                "The signed body does not describe this scan on this deployment.",
                http_status=409,
                details={"mismatched_fields": mismatched},
            )
        # Once the platform attestation exists, a counterparty must bind to it.
        # Accepting an unbound signature afterwards would let the same commitment
        # be presented as if it referenced a different packet attestation.
        if (
            attestation_uid
            and str(body.get("platform_attestation_uid") or "").lower()
            != str(attestation_uid).lower()
        ):
            raise CoAttestationError(
                "PLATFORM_ATTESTATION_BINDING_MISMATCH",
                "The signed body must reference this scan's platform attestation.",
                http_status=409,
                details={"expected_platform_attestation_uid": attestation_uid},
            )
        _coerce_role(body.get("party_role"))
        _coerce_decision(body.get("decision"))
        signer_address = _normalize_address(body.get("signer_address"))
        if body.get("decision_note_sha256") is not None:
            _normalize_sha256(body.get("decision_note_sha256"), field="decision_note_sha256")
        nonce = str(body.get("nonce") or "")
        if not 16 <= len(nonce) <= 80:
            raise CoAttestationError(
                "INVALID_NONCE",
                "The body nonce must be between 16 and 80 characters.",
                http_status=422,
            )
        self._check_freshness(body.get("issued_at"))
        return {"signer_address": signer_address, "platform_attestation_uid": attestation_uid}

    def _check_freshness(self, issued_at: object) -> None:
        try:
            issued = datetime.fromisoformat(str(issued_at))
        except (TypeError, ValueError) as exc:
            raise CoAttestationError(
                "INVALID_ISSUED_AT",
                "The body issued_at must be an ISO-8601 timestamp.",
                http_status=422,
            ) from exc
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=UTC)
        now = _utcnow()
        max_age = timedelta(seconds=self.settings.counterparty_attestation_max_age_seconds)
        if issued > now + timedelta(seconds=60):
            raise CoAttestationError(
                "SIGNATURE_ISSUED_IN_FUTURE",
                "The body issued_at is in the future.",
                http_status=422,
            )
        if now - issued > max_age:
            raise CoAttestationError(
                "SIGNATURE_EXPIRED",
                "This signature is older than the deployment's acceptance window.",
                http_status=409,
                details={"max_age_seconds": int(max_age.total_seconds())},
            )

    def record(self, db, *, scan, body: dict, signature: str) -> dict:
        """Verify one counterparty signature and queue its public commitment."""
        from app.models import CounterpartyAttestation

        self._require_enabled()
        deployment_id = self.blockchain.status()["deployment_id"]
        validated = self._validate_body(body=body, scan=scan, deployment_id=deployment_id)
        digest = body_hash(body)

        try:
            verification = self.verifier.verify(body_hash_sha256=digest, signature=signature)
        except CounterpartySignatureUnavailable as exc:
            raise CoAttestationError(
                "COUNTERPARTY_ATTESTATION_UNAVAILABLE",
                "This deployment cannot verify counterparty signatures.",
                http_status=409,
                details={"reason": str(exc)},
            ) from exc
        if not verification.verified or not verification.signer_address:
            raise CoAttestationError(
                "SIGNATURE_INVALID",
                "The signature could not be verified against the signed body.",
                http_status=422,
                details={"reason": verification.reason},
            )
        if verification.signer_address != validated["signer_address"]:
            raise CoAttestationError(
                "SIGNER_ADDRESS_MISMATCH",
                "The recovered signing address is not the address named in the body.",
                http_status=422,
                details={"recovered_address": verification.signer_address},
            )

        membership = self.resolve_membership(
            db, tenant_id=scan.tenant_id, address=verification.signer_address
        )
        if not membership["permitted"]:
            raise CoAttestationError(
                "MEMBER_NOT_ACTIVE",
                "This address is not an active member of the attestation network.",
                http_status=403,
                details={"membership": membership},
            )

        existing = db.scalar(
            select(CounterpartyAttestation).where(
                CounterpartyAttestation.tenant_id == scan.tenant_id,
                CounterpartyAttestation.body_hash_sha256 == digest,
            )
        )
        if existing is not None:
            # Replaying an identical signed body is not an error; it must not
            # create a second commitment or a second transaction.
            return self.describe(db, existing)

        row = CounterpartyAttestation(
            tenant_id=scan.tenant_id,
            scan_id=scan.id,
            member_id=membership.get("member_id"),
            signer_address=verification.signer_address,
            party_role=str(body["party_role"]),
            decision=str(body["decision"]),
            packet_hash_sha256=str(body["packet_hash_sha256"]),
            platform_attestation_uid=validated["platform_attestation_uid"],
            body=body,
            body_hash_sha256=digest,
            signature=str(signature),
            signature_alg=verification.algorithm,
            membership_evidence=membership,
            state=str(CounterpartyAttestationState.SIGNED),
        )
        db.add(row)
        db.commit()

        self._record_integrity_event(db, row=row, event_type=CO_ATTESTATION_EVENT)
        self.enqueue_anchor(db, row)
        db.refresh(row)
        return self.describe(db, row)

    def enqueue_anchor(self, db, row) -> str | None:
        """Queue the public commitment; the signature is already durable."""
        if row.anchor_job_id or self.blockchain is None:
            return row.anchor_job_id
        job_id = self.blockchain.enqueue_counterparty_attestation(
            body_hash=row.body_hash_sha256,
            attestation_id=row.id,
            tenant_id=row.tenant_id,
            scan_id=row.scan_id,
            signer_address=row.signer_address,
            ref_uid=row.platform_attestation_uid,
        )
        if job_id is None:
            return None
        row.anchor_job_id = job_id
        row.state = str(CounterpartyAttestationState.ANCHOR_PENDING)
        db.commit()
        return job_id

    def withdraw(self, db, row, *, reason: str | None = None) -> dict:
        """Mark a commitment withdrawn without erasing the signature it contains."""
        if str(row.state) == str(CounterpartyAttestationState.WITHDRAWN):
            return self.describe(db, row)
        row.state = str(CounterpartyAttestationState.WITHDRAWN)
        row.withdrawn_at = _utcnow()
        db.commit()
        self._record_integrity_event(
            db,
            row=row,
            event_type=CO_ATTESTATION_WITHDRAWN_EVENT,
            extra={"reason": reason} if reason else None,
        )
        db.refresh(row)
        return self.describe(db, row)

    def _record_integrity_event(
        self, db, *, row, event_type: str, extra: dict | None = None
    ) -> None:
        """Append the commitment to the signed transparency log.

        A counterparty commitment therefore reaches the chain twice: directly as
        its own attestation, and indirectly inside the next checkpoint root.
        """
        from app.services.blockchain import record_integrity_event

        try:
            record_integrity_event(
                db,
                signer=self.signer,
                transparency=self.transparency,
                blockchain=self.blockchain,
                tenant_id=row.tenant_id,
                event_type=event_type,
                subject_type="counterparty_attestation",
                subject_id=row.id,
                attributes={
                    "scan_id": row.scan_id,
                    "signer_address": row.signer_address,
                    "party_role": str(row.party_role),
                    "decision": str(row.decision),
                    "packet_hash_sha256": row.packet_hash_sha256,
                    "body_hash_sha256": row.body_hash_sha256,
                    "platform_attestation_uid": row.platform_attestation_uid,
                    **(extra or {}),
                },
            )
        except Exception:
            # The counterparty's signature is already durable. Losing the log
            # append is recoverable by the blockchain dispatcher's reconciler.
            db.rollback()
            logger.exception("counterparty_integrity_event_failed attestation_id=%s", row.id)

    # -- read ------------------------------------------------------------

    def describe(self, db, row) -> dict:
        """Return the commitment with everything needed to re-verify it."""
        from app.models import BlockchainAnchorJob

        job = db.get(BlockchainAnchorJob, row.anchor_job_id) if row.anchor_job_id else None
        receipt = dict((job.receipt or {}).get("receipt") or {}) if job is not None else {}
        recomputed = None
        try:
            recomputed = canonical_digest(row.body)
        except CanonicalizationError:  # pragma: no cover - stored bodies are canonical
            recomputed = None
        return {
            "schema": "creatorproof.counterparty_attestation_view.v1",
            "id": row.id,
            "scan_id": row.scan_id,
            "state": str(row.state),
            "decision": str(row.decision),
            "party_role": str(row.party_role),
            "signer_address": row.signer_address,
            "member_id": row.member_id,
            "packet_hash_sha256": row.packet_hash_sha256,
            "platform_attestation_uid": row.platform_attestation_uid,
            "body": row.body,
            "body_hash_sha256": row.body_hash_sha256,
            "signature": row.signature,
            "signature_alg": row.signature_alg,
            "membership": row.membership_evidence,
            "checks": {
                "body_hash_matches_body": recomputed == row.body_hash_sha256,
                "signature_verified_at_submission": True,
                "member_permitted_at_submission": bool(
                    (row.membership_evidence or {}).get("permitted")
                ),
                "binds_platform_attestation": bool(row.platform_attestation_uid),
                "on_chain_commitment_matches_body_hash": (
                    receipt.get("commitment_hash_sha256") == row.body_hash_sha256
                    if receipt
                    else None
                ),
                "on_chain_ref_uid_matches_platform_attestation": (
                    None
                    if not receipt or not row.platform_attestation_uid
                    else str(receipt.get("ref_uid") or "").lower()
                    == str(row.platform_attestation_uid).lower()
                ),
            },
            "public_chain": {
                "job_id": row.anchor_job_id,
                "job_state": str(job.state) if job is not None else None,
                "attestation_uid": receipt.get("attestation_uid"),
                "transaction_hash": receipt.get("transaction_hash"),
                "chain_id": receipt.get("chain_id"),
                "explorer": receipt.get("explorer"),
                "anchor_conditions_met": receipt.get("anchor_conditions_met"),
            },
            "withdrawn_at": row.withdrawn_at.isoformat() if row.withdrawn_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "trust_note": TRUST_NOTE,
        }


def _coerce_role(value: object) -> NetworkMemberRole:
    try:
        return NetworkMemberRole(str(value))
    except ValueError as exc:
        raise CoAttestationError(
            "UNKNOWN_PARTY_ROLE",
            "The party role is not one this network recognizes.",
            http_status=422,
            details={"allowed": [role.value for role in NetworkMemberRole]},
        ) from exc


def _coerce_decision(value: object) -> CounterpartyDecision:
    try:
        return CounterpartyDecision(str(value))
    except ValueError as exc:
        raise CoAttestationError(
            "UNKNOWN_DECISION",
            "The decision is not one this network recognizes.",
            http_status=422,
            details={"allowed": [decision.value for decision in CounterpartyDecision]},
        ) from exc
