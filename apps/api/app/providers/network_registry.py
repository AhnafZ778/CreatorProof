"""Who may co-attest, according to the chain.

Membership is deliberately readable by anyone: a reviewer can check whether the
address that signed a co-attestation was an active member at the time, without
asking CreatorProof. The local ``network_members`` table holds the identity
metadata that must stay off chain, but when a registry contract is configured
the contract, not the table, decides whether an address may attest.
"""

from __future__ import annotations

import logging

from app.domain.platform import (
    NETWORK_MEMBER_ROLE_CODES,
    NETWORK_MEMBER_STATUS_CODES,
    NetworkMemberStatus,
)

logger = logging.getLogger("creatorproof.network_registry")

MEMBER_REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "memberStatus",
        "outputs": [
            {"internalType": "uint8", "name": "status", "type": "uint8"},
            {"internalType": "uint8", "name": "role", "type": "uint8"},
            {"internalType": "bytes32", "name": "orgId", "type": "bytes32"},
            {"internalType": "uint64", "name": "enrolledAt", "type": "uint64"},
            {"internalType": "uint64", "name": "updatedAt", "type": "uint64"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "account", "type": "address"}],
        "name": "isActiveMember",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "governor",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "activeMemberCount",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]


def _field(value: object, name: str, index: int, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    try:
        return value[index]  # type: ignore[index]
    except (TypeError, IndexError, KeyError):
        return default


class NullMemberRegistry:
    """Used when no registry contract is configured for this deployment."""

    name = "member-registry-not-configured"
    configured = False

    def lookup(self, address: str) -> dict:
        del address
        return {"checked": False, "reason": "MEMBER_REGISTRY_NOT_CONFIGURED"}

    def status(self) -> dict:
        return {"provider": self.name, "configured": False, "reason": None}


class OnChainMemberRegistry:
    """Read membership straight from the registry contract."""

    name = "creatorproof-member-registry-v1"
    configured = True

    def __init__(self, *, connect, contract_address: str) -> None:
        # ``connect`` is supplied by the EAS provider so RPC failover, timeouts and
        # endpoint configuration have exactly one implementation.
        self._connect = connect
        self.contract_address = contract_address

    def lookup(self, address: str) -> dict:
        """Return the on-chain membership record, or why it could not be read."""
        try:
            web3 = self._connect()
            checksum = web3.to_checksum_address(address)
            contract = web3.eth.contract(
                address=web3.to_checksum_address(self.contract_address),
                abi=MEMBER_REGISTRY_ABI,
            )
            record = contract.functions.memberStatus(checksum).call()
        except Exception as exc:
            logger.warning("member_registry_read_failed error=%s", type(exc).__name__)
            return {
                "checked": False,
                "reason": f"MEMBER_REGISTRY_READ_FAILED:{type(exc).__name__}",
                "registry_address": self.contract_address,
            }
        status_code = int(_field(record, "status", 0, 0) or 0)
        role_code = int(_field(record, "role", 1, 0) or 0)
        org_id = _field(record, "orgId", 2, b"")
        status = NETWORK_MEMBER_STATUS_CODES.get(status_code, NetworkMemberStatus.UNKNOWN)
        role = NETWORK_MEMBER_ROLE_CODES.get(role_code)
        return {
            "checked": True,
            "reason": None,
            "registry_address": self.contract_address,
            "address": str(address).lower(),
            "status": str(status),
            "active": status == NetworkMemberStatus.ACTIVE,
            "role": str(role) if role is not None else None,
            "org_id": org_id.hex() if isinstance(org_id, (bytes, bytearray)) else str(org_id),
            "enrolled_at": int(_field(record, "enrolledAt", 3, 0) or 0),
            "updated_at": int(_field(record, "updatedAt", 4, 0) or 0),
        }

    def status(self) -> dict:
        governor = None
        active_members = None
        reason = None
        try:
            web3 = self._connect()
            contract = web3.eth.contract(
                address=web3.to_checksum_address(self.contract_address),
                abi=MEMBER_REGISTRY_ABI,
            )
            governor = str(contract.functions.governor().call())
            active_members = int(contract.functions.activeMemberCount().call())
        except Exception as exc:
            reason = f"MEMBER_REGISTRY_READ_FAILED:{type(exc).__name__}"
        return {
            "provider": self.name,
            "configured": True,
            "registry_address": self.contract_address,
            "governor": governor,
            "active_member_count": active_members,
            "reason": reason,
            "scope": "MEMBERSHIP_AND_PERMISSION_ONLY_NOT_OWNERSHIP",
        }


def build_member_registry(settings, proof_anchor) -> NullMemberRegistry | OnChainMemberRegistry:
    """Attach the registry to the configured chain client, or report it absent."""
    address = getattr(settings, "eas_member_registry_address", "")
    connect = getattr(proof_anchor, "_connect", None)
    if not address or connect is None or not getattr(proof_anchor, "available", False):
        return NullMemberRegistry()
    return OnChainMemberRegistry(connect=connect, contract_address=address)
