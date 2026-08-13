"""Counterparty signature verification.

A co-attestation is only worth anchoring if CreatorProof could not have produced
it alone. The counterparty signs an EIP-712 payload with its own secp256k1 key
and CreatorProof recovers the signing address; nothing here trusts a session, an
API key, or a self-declared address.

The typed-data domain pins ``chainId`` and ``verifyingContract`` (the member
registry), so a signature collected for one deployment cannot be replayed
against another network or another registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger("creatorproof.counterparty")

SIGNATURE_ALGORITHM = "EIP712_SECP256K1"
PRIMARY_TYPE = "CounterpartyAttestation"
# The signed struct is deliberately one field. Every other value a verifier needs
# lives inside the canonical body whose SHA-256 digest this is, so the typed data
# cannot drift out of step with what actually gets committed on chain.
TYPES = {
    PRIMARY_TYPE: [{"name": "bodyHash", "type": "bytes32"}],
}


@dataclass(frozen=True, slots=True)
class SignatureVerification:
    verified: bool
    signer_address: str | None
    reason: str | None = None
    algorithm: str = SIGNATURE_ALGORITHM


class CounterpartySignatureUnavailable(RuntimeError):
    """Raised when this deployment cannot verify counterparty signatures at all."""


class Eip712CounterpartyVerifier:
    """Recover the EVM address that signed a co-attestation body hash."""

    name = "eip712-counterparty-verifier-v1"

    def __init__(
        self,
        *,
        domain_name: str,
        domain_version: str,
        chain_id: int | None,
        verifying_contract: str,
    ) -> None:
        self.domain_name = domain_name
        self.domain_version = domain_version
        self.chain_id = chain_id
        self.verifying_contract = verifying_contract
        self.available = False
        self.unavailable_reason: str | None = None
        if chain_id is None:
            self.unavailable_reason = "COUNTERPARTY_CHAIN_ID_NOT_PINNED"
            return
        if not verifying_contract:
            self.unavailable_reason = "COUNTERPARTY_VERIFYING_CONTRACT_NOT_CONFIGURED"
            return
        try:
            from eth_account import Account  # type: ignore  # noqa: F401
            from eth_account.messages import encode_typed_data  # type: ignore  # noqa: F401
        except ImportError:
            self.unavailable_reason = "COUNTERPARTY_SIGNATURE_RUNTIME_UNAVAILABLE"
            return
        self.available = True

    def typed_data(self, body_hash_sha256: str) -> dict:
        """Return the exact structure a counterparty wallet must sign."""
        return {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                **TYPES,
            },
            "primaryType": PRIMARY_TYPE,
            "domain": {
                "name": self.domain_name,
                "version": self.domain_version,
                "chainId": self.chain_id,
                "verifyingContract": self.verifying_contract,
            },
            "message": {"bodyHash": f"0x{body_hash_sha256}"},
        }

    def verify(self, *, body_hash_sha256: str, signature: str) -> SignatureVerification:
        if not self.available:
            raise CounterpartySignatureUnavailable(
                self.unavailable_reason or "COUNTERPARTY_SIGNATURE_UNAVAILABLE"
            )
        from eth_account import Account  # type: ignore
        from eth_account.messages import encode_typed_data  # type: ignore

        payload = self.typed_data(body_hash_sha256)
        try:
            message = encode_typed_data(
                domain_data=payload["domain"],
                message_types=TYPES,
                message_data=payload["message"],
            )
            recovered = Account.recover_message(message, signature=signature)
        except Exception as exc:
            # The failure reason is derived from the exception type only; a raw
            # signature-library message can echo caller-controlled input.
            logger.info("counterparty_signature_rejected error=%s", type(exc).__name__)
            return SignatureVerification(
                verified=False,
                signer_address=None,
                reason=f"SIGNATURE_UNREADABLE:{type(exc).__name__}",
            )
        return SignatureVerification(verified=True, signer_address=str(recovered).lower())

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "reason": self.unavailable_reason,
            "algorithm": SIGNATURE_ALGORITHM,
            "primary_type": PRIMARY_TYPE,
            "domain": {
                "name": self.domain_name,
                "version": self.domain_version,
                "chain_id": self.chain_id,
                "verifying_contract": self.verifying_contract or None,
            },
        }


def build_counterparty_verifier(settings) -> Eip712CounterpartyVerifier:
    return Eip712CounterpartyVerifier(
        domain_name=settings.counterparty_attestation_domain_name,
        domain_version=settings.counterparty_attestation_domain_version,
        chain_id=settings.eas_chain_id,
        verifying_contract=settings.eas_member_registry_address,
    )
