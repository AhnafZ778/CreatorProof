from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from app.domain.enums import AnchorStatus
from app.providers.contracts import ProofReceipt

logger = logging.getLogger("creatorproof.proof")


def _bytes32(value: str) -> bytes:
    decoded = bytes.fromhex(value.removeprefix("0x"))
    if len(decoded) != 32:
        raise ValueError("Expected a bytes32 hex value")
    return decoded


def _leaf_hash(packet_hash: str) -> bytes:
    return hashlib.sha256(b"\x00" + bytes.fromhex(packet_hash)).digest()


def _node_hash(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _root_and_proof(leaves: list[bytes], index: int) -> tuple[bytes, list[dict]]:
    if not leaves or not 0 <= index < len(leaves):
        raise ValueError("Invalid Merkle leaf index")
    level = list(leaves)
    cursor = index
    proof: list[dict] = []
    while len(level) > 1:
        if cursor % 2 == 0 and cursor + 1 < len(level):
            proof.append({"side": "right", "hash": level[cursor + 1].hex()})
        elif cursor % 2 == 1:
            proof.append({"side": "left", "hash": level[cursor - 1].hex()})
        next_level = [
            _node_hash(level[offset], level[offset + 1])
            if offset + 1 < len(level)
            else level[offset]
            for offset in range(0, len(level), 2)
        ]
        cursor //= 2
        level = next_level
    return level[0], proof


def verify_merkle_receipt(packet_hash: str, root_hex: str, proof: list[dict]) -> bool:
    try:
        value = _leaf_hash(packet_hash)
        for item in proof:
            sibling = bytes.fromhex(str(item["hash"]))
            value = (
                _node_hash(sibling, value) if item["side"] == "left" else _node_hash(value, sibling)
            )
        expected_root = bytes.fromhex(root_hex)
    except (KeyError, TypeError, ValueError):
        return False
    return value == expected_root


class NoopProofAnchor:
    name = "not-requested"

    def anchor(self, packet_hash: str) -> ProofReceipt:
        del packet_hash
        return ProofReceipt(
            status=AnchorStatus.NOT_REQUESTED,
            provider=self.name,
            receipt=None,
        )

    def status(self) -> dict:
        return {"provider": self.name, "available": False, "scope": "NONE", "reason": None}


class MerkleTransparencyAnchor:
    """Append-only local transparency receipt using RFC6962-style domain separation.

    This is cryptographic audit infrastructure, not a blockchain. The distinction is
    recorded in every receipt and the UI must preserve it.
    """

    name = "local-merkle-transparency-log-v1"
    _lock = threading.Lock()

    def __init__(self, log_path: Path) -> None:
        self.log_path = Path(log_path)
        self.available = True

    def _packet_hashes(self) -> list[str]:
        if not self.log_path.exists():
            return []
        hashes: list[str] = []
        for line in self.log_path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
                value = str(payload["packet_hash_sha256"])
                if len(value) == 64:
                    bytes.fromhex(value)
                    hashes.append(value)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return hashes

    def anchor(self, packet_hash: str) -> ProofReceipt:
        if len(packet_hash) != 64:
            return ProofReceipt(
                status=AnchorStatus.FAILED,
                provider=self.name,
                receipt={"error_code": "INVALID_PACKET_HASH"},
            )
        with self._lock:
            hashes = self._packet_hashes()
            hashes.append(packet_hash)
            leaves = [_leaf_hash(value) for value in hashes]
            root, proof = _root_and_proof(leaves, len(leaves) - 1)
            timestamp = datetime.now(UTC).isoformat()
            record = {
                "schema": "creatorproof.transparency_leaf.v1",
                "index": len(hashes) - 1,
                "packet_hash_sha256": packet_hash,
                "leaf_hash_sha256": leaves[-1].hex(),
                "tree_size": len(hashes),
                "root_sha256": root.hex(),
                "recorded_at": timestamp,
            }
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with self.log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")))
                    handle.write("\n")
            except OSError:
                return ProofReceipt(
                    status=AnchorStatus.FAILED,
                    provider=self.name,
                    receipt={"error_code": "TRANSPARENCY_LOG_WRITE_FAILED"},
                )
        verified = verify_merkle_receipt(packet_hash, root.hex(), proof)
        return ProofReceipt(
            status=AnchorStatus.ANCHORED if verified else AnchorStatus.FAILED,
            provider=self.name,
            receipt={
                **record,
                "inclusion_proof": proof,
                "inclusion_verified": verified,
                "anchor_scope": "LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN",
            },
        )

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": True,
            "scope": "LOCAL_TRANSPARENCY_LOG",
            "reason": "NOT_A_BLOCKCHAIN",
        }


_EAS_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"internalType": "bytes32", "name": "schema", "type": "bytes32"},
                    {
                        "components": [
                            {"internalType": "address", "name": "recipient", "type": "address"},
                            {"internalType": "uint64", "name": "expirationTime", "type": "uint64"},
                            {"internalType": "bool", "name": "revocable", "type": "bool"},
                            {"internalType": "bytes32", "name": "refUID", "type": "bytes32"},
                            {"internalType": "bytes", "name": "data", "type": "bytes"},
                            {"internalType": "uint256", "name": "value", "type": "uint256"},
                        ],
                        "internalType": "struct AttestationRequestData",
                        "name": "data",
                        "type": "tuple",
                    },
                ],
                "internalType": "struct AttestationRequest",
                "name": "request",
                "type": "tuple",
            }
        ],
        "name": "attest",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "recipient", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "attester", "type": "address"},
            {"indexed": False, "internalType": "bytes32", "name": "uid", "type": "bytes32"},
            {"indexed": True, "internalType": "bytes32", "name": "schemaUID", "type": "bytes32"},
        ],
        "name": "Attested",
        "type": "event",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "uid", "type": "bytes32"}],
        "name": "isAttestationValid",
        "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "uid", "type": "bytes32"}],
        "name": "getAttestation",
        "outputs": [
            {
                "components": [
                    {"internalType": "bytes32", "name": "uid", "type": "bytes32"},
                    {"internalType": "bytes32", "name": "schema", "type": "bytes32"},
                    {"internalType": "uint64", "name": "time", "type": "uint64"},
                    {
                        "internalType": "uint64",
                        "name": "expirationTime",
                        "type": "uint64",
                    },
                    {
                        "internalType": "uint64",
                        "name": "revocationTime",
                        "type": "uint64",
                    },
                    {"internalType": "bytes32", "name": "refUID", "type": "bytes32"},
                    {"internalType": "address", "name": "recipient", "type": "address"},
                    {"internalType": "address", "name": "attester", "type": "address"},
                    {"internalType": "bool", "name": "revocable", "type": "bool"},
                    {"internalType": "bytes", "name": "data", "type": "bytes"},
                ],
                "internalType": "struct Attestation",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "getSchemaRegistry",
        "outputs": [
            {
                "internalType": "contract ISchemaRegistry",
                "name": "",
                "type": "address",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    },
]


_SCHEMA_REGISTRY_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "uid", "type": "bytes32"}],
        "name": "getSchema",
        "outputs": [
            {
                "components": [
                    {"internalType": "bytes32", "name": "uid", "type": "bytes32"},
                    {
                        "internalType": "contract ISchemaResolver",
                        "name": "resolver",
                        "type": "address",
                    },
                    {"internalType": "bool", "name": "revocable", "type": "bool"},
                    {"internalType": "string", "name": "schema", "type": "string"},
                ],
                "internalType": "struct SchemaRecord",
                "name": "",
                "type": "tuple",
            }
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


_ZERO_BYTES32 = bytes(32)


def _canonical_bytes32(value: object) -> str:
    """Return a lower-case, 0x-prefixed bytes32 value or fail closed."""
    if isinstance(value, str):
        decoded = _bytes32(value)
    elif isinstance(value, (bytes, bytearray)):
        decoded = bytes(value)
        if len(decoded) != 32:
            raise ValueError("Expected a bytes32 value")
    else:
        try:
            decoded = bytes(value)  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError("Expected a bytes32 value") from exc
        if len(decoded) != 32:
            raise ValueError("Expected a bytes32 value")
    return f"0x{decoded.hex()}"


def _canonical_packet_hash(value: str) -> str:
    """Canonical packet commitments omit 0x in evidence packets and receipts."""
    return _canonical_bytes32(value).removeprefix("0x")


_COMMITMENT_HASH_FIELDS = {
    "TRANSPARENCY_CHECKPOINT": "checkpoint_hash_sha256",
    "COUNTERPARTY_ATTESTATION": "coattestation_hash_sha256",
}


_PRIVACY_NOTES = {
    "EVIDENCE_PACKET": (
        "Only the canonical packet hash is committed. No media, claimant identity, "
        "detector output or evidence payload is placed on chain."
    ),
    "TRANSPARENCY_CHECKPOINT": (
        "Only the signed transparency checkpoint hash is committed. No log entries, "
        "media, claimant identity or evidence payload is placed on chain."
    ),
    "COUNTERPARTY_ATTESTATION": (
        "Only the counterparty commitment hash is committed. The decision body, the "
        "signing organization and any note stay off chain."
    ),
}

_TRUST_NOTES = {
    "EVIDENCE_PACKET": (
        "The attestation commits this packet identity and its time. It does not "
        "establish that the underlying evidence or any rights claim is true."
    ),
    "TRANSPARENCY_CHECKPOINT": (
        "The attestation commits this packet identity and its time. It does not "
        "establish that the underlying evidence or any rights claim is true."
    ),
    "COUNTERPARTY_ATTESTATION": (
        "The attestation commits that a network member signed this decision at this "
        "time. It does not establish that the decision was correct, that the member "
        "held authority, or that any rights claim is true."
    ),
}


def _commitment_hash_alias(commitment_type: str, value: object) -> dict:
    """Name a commitment after what it commits to, alongside the generic field.

    Receipts written before a commitment type existed keep their original field
    name, so verifiers and stored packets stay readable across versions.
    """
    return {_COMMITMENT_HASH_FIELDS.get(commitment_type, "packet_hash_sha256"): value}


def _field(value: object, name: str, index: int, default=None):
    if isinstance(value, dict):
        return value.get(name, default)
    try:
        return value[name]  # type: ignore[index]
    except (KeyError, TypeError, IndexError):
        pass
    try:
        return value[index]  # type: ignore[index]
    except (TypeError, IndexError):
        return default


def _address_equal(left: object, right: object) -> bool:
    return bool(left and right and str(left).lower() == str(right).lower())


_TRANSIENT_CHAIN_ERRORS = (
    "timeout",
    "timed out",
    "connection",
    "temporarily unavailable",
    "nonce too low",
    "replacement transaction underpriced",
    "already known",
    "rate limit",
    "too many requests",
    "503",
    "502",
)


def _is_transient_chain_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_CHAIN_ERRORS)


class EASProofAnchor:
    """Commit one canonical bytes32 value through Ethereum Attestation Service.

    A successful transaction alone is not enough. CreatorProof confirms an anchor
    only after the configured confirmation depth, a canonical-receipt check, and
    a full read-back of the EAS attestation fields and encoded commitment. Protocol
    safe/finalized state is reported separately when the RPC supports those tags.
    """

    name = "ethereum-attestation-service-onchain-v1"
    _nonce_lock = threading.Lock()
    _prepared_transactions: dict[str, dict] = {}
    _prepared_cache_limit = 512
    _preflight_status_ttl_seconds = 30.0

    def __init__(
        self,
        *,
        rpc_url: str,
        contract_address: str,
        schema_uid: str,
        private_key: str,
        recipient: str,
        explorer_tx_base_url: str,
        chain_id: int | None,
        timeout_seconds: int,
        network_label: str = "",
        explorer_address_base_url: str = "",
        explorer_attestation_base_url: str = "",
        required_confirmations: int = 1,
        max_attempts: int = 3,
        retry_backoff_seconds: float = 3.0,
        max_fee_per_gas_gwei: float = 0.0,
        schema_registry_address: str = "",
        schema_definition: str = "bytes32 packetHash",
        expected_contract_code_sha256: str = "",
        rpc_urls: list[str] | tuple[str, ...] | None = None,
        required_attester_address: str = "",
        checkpoint_schema_uid: str = "",
        checkpoint_schema_definition: str = "bytes32 checkpointHash",
        coattestation_schema_uid: str = "",
        coattestation_schema_definition: str = "bytes32 coAttestationHash",
        member_registry_address: str = "",
        finality_policy: str = "confirmation_depth",
    ) -> None:
        urls = [rpc_url, *(rpc_urls or ())]
        self.rpc_urls = tuple(dict.fromkeys(value.strip() for value in urls if value.strip()))
        # Kept for callers that inspect the legacy attribute. It is never returned by status().
        self.rpc_url = self.rpc_urls[0] if self.rpc_urls else ""
        self.contract_address = contract_address
        self.schema_uid = schema_uid
        self.private_key = private_key
        self.recipient = recipient
        self.schema_registry_address = schema_registry_address
        self.schema_definition = schema_definition.strip()
        self.checkpoint_schema_uid = checkpoint_schema_uid
        self.checkpoint_schema_definition = checkpoint_schema_definition.strip()
        self.coattestation_schema_uid = coattestation_schema_uid
        self.coattestation_schema_definition = coattestation_schema_definition.strip()
        self.member_registry_address = member_registry_address
        self.expected_contract_code_sha256 = expected_contract_code_sha256.lower().removeprefix(
            "0x"
        )
        self.required_attester_address = required_attester_address
        self.explorer_tx_base_url = explorer_tx_base_url.rstrip("/")
        self.explorer_address_base_url = explorer_address_base_url.rstrip("/")
        self.explorer_attestation_base_url = explorer_attestation_base_url.rstrip("/")
        self.chain_id = chain_id
        self.timeout_seconds = timeout_seconds
        self.network_label = network_label
        self.required_confirmations = max(0, required_confirmations)
        if finality_policy not in {"confirmation_depth", "safe", "finalized"}:
            raise ValueError("Unsupported EAS finality policy")
        self.finality_policy = finality_policy
        self.max_attempts = max(1, max_attempts)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self.max_fee_per_gas_wei = int(max_fee_per_gas_gwei * 1e9) if max_fee_per_gas_gwei else 0
        self.available = False
        self.unavailable_reason: str | None = None
        self._web3 = None
        self.attester_address: str | None = None
        self._last_preflight: dict | None = None
        self._last_preflight_at: str | None = None
        self._last_preflight_monotonic: float | None = None
        self._preflight_lock = threading.Lock()
        if not all((self.rpc_urls, contract_address, schema_uid, private_key, recipient)):
            self.unavailable_reason = "EAS_CONFIGURATION_INCOMPLETE"
            return
        try:
            from eth_account import Account  # type: ignore
            from web3 import Web3  # type: ignore

            self._web3 = Web3
            if not Web3.is_address(contract_address) or not Web3.is_address(recipient):
                raise ValueError("invalid EAS contract or recipient")
            if schema_registry_address and not Web3.is_address(schema_registry_address):
                raise ValueError("invalid EAS schema registry")
            _bytes32(schema_uid)
            if checkpoint_schema_uid:
                _bytes32(checkpoint_schema_uid)
            if coattestation_schema_uid:
                _bytes32(coattestation_schema_uid)
            if member_registry_address and not Web3.is_address(member_registry_address):
                raise ValueError("invalid member registry address")
            if self.expected_contract_code_sha256:
                _canonical_packet_hash(self.expected_contract_code_sha256)
            self.attester_address = Account.from_key(private_key).address
            if required_attester_address:
                if not Web3.is_address(required_attester_address):
                    raise ValueError("invalid required EAS attester")
                if not _address_equal(self.attester_address, required_attester_address):
                    self.unavailable_reason = "EAS_ATTESTER_KEY_MISMATCH"
                    return
            self.available = True
        except (ImportError, TypeError, ValueError) as exc:
            self.unavailable_reason = f"EAS_RUNTIME_UNAVAILABLE:{type(exc).__name__}"

    def _connect(self):
        if self._web3 is None:
            raise RuntimeError("EAS_RUNTIME_UNAVAILABLE")
        first = None
        for url in self.rpc_urls:
            try:
                try:
                    provider = self._web3.HTTPProvider(
                        url, request_kwargs={"timeout": self.timeout_seconds}
                    )
                except TypeError:  # pragma: no cover - supports small test doubles/older web3
                    provider = self._web3.HTTPProvider(url)
                web3 = self._web3(provider)
                first = first or web3
                if web3.is_connected():
                    return web3
            except Exception as exc:
                logger.warning("eas_rpc_endpoint_unavailable error=%s", type(exc).__name__)
        if first is not None:
            return first
        raise RuntimeError("EAS_RPC_UNAVAILABLE")

    def _contract(self, web3):
        return web3.eth.contract(
            address=self._web3.to_checksum_address(self.contract_address), abi=_EAS_ABI
        )

    def _explorer_urls(self, tx_hex: str, uid: str | None) -> dict:
        tx_hex = _canonical_bytes32(tx_hex)
        return {
            "transaction_url": (
                f"{self.explorer_tx_base_url}/{tx_hex}" if self.explorer_tx_base_url else None
            ),
            "attester_url": (
                f"{self.explorer_address_base_url}/{self.attester_address}"
                if self.explorer_address_base_url and self.attester_address
                else None
            ),
            "attestation_url": (
                f"{self.explorer_attestation_base_url}/{uid}"
                if self.explorer_attestation_base_url and uid
                else None
            ),
        }

    def _contract_code_status(self, web3, address: str) -> dict:
        code = bytes(web3.eth.get_code(self._web3.to_checksum_address(address)))
        digest = hashlib.sha256(code).hexdigest() if code else None
        expected = self.expected_contract_code_sha256 or None
        return {
            "has_code": bool(code),
            "code_sha256": digest,
            "code_matches_expected": None if expected is None else digest == expected,
        }

    def _schema_status(
        self,
        web3,
        eas_contract,
        *,
        schema_uid: str,
        schema_definition: str,
        expected_revocable: bool,
    ) -> dict:
        registry_address = self.schema_registry_address
        if not registry_address:
            registry_address = str(eas_contract.functions.getSchemaRegistry().call())
        if not self._web3.is_address(registry_address):
            raise RuntimeError("EAS_SCHEMA_REGISTRY_INVALID")
        registry_code = bytes(web3.eth.get_code(self._web3.to_checksum_address(registry_address)))
        if not registry_code:
            return {
                "schema_registry_address": registry_address,
                "schema_registry_has_code": False,
                "schema_registered": False,
                "schema_definition_matches": False,
            }
        registry = web3.eth.contract(
            address=self._web3.to_checksum_address(registry_address),
            abi=_SCHEMA_REGISTRY_ABI,
        )
        record = registry.functions.getSchema(_bytes32(schema_uid)).call()
        record_uid = _canonical_bytes32(_field(record, "uid", 0, _ZERO_BYTES32))
        definition = str(_field(record, "schema", 3, ""))
        return {
            "schema_registry_address": registry_address,
            "schema_registry_has_code": True,
            "schema_registered": record_uid == _canonical_bytes32(schema_uid),
            "schema_definition": definition,
            "schema_definition_matches": definition == schema_definition,
            "schema_revocable": bool(_field(record, "revocable", 2, False)),
            "schema_revocability_matches": (
                bool(_field(record, "revocable", 2, False)) == expected_revocable
            ),
        }

    def _commitment_policy(self, commitment_type: str | None) -> dict:
        normalized = (commitment_type or "EVIDENCE_PACKET").strip().upper()
        if normalized in {"EVIDENCE_PACKET", "CANONICAL_EVIDENCE_PACKET_SHA256"}:
            return {
                "commitment_type": "EVIDENCE_PACKET",
                "schema_uid": self.schema_uid,
                "schema_definition": self.schema_definition,
                "revocable": True,
                "supports_ref_uid": False,
                "anchor_scope": "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
            }
        if normalized == "TRANSPARENCY_CHECKPOINT":
            if not self.checkpoint_schema_uid:
                raise RuntimeError("EAS_CHECKPOINT_SCHEMA_NOT_CONFIGURED")
            return {
                "commitment_type": "TRANSPARENCY_CHECKPOINT",
                "schema_uid": self.checkpoint_schema_uid,
                "schema_definition": self.checkpoint_schema_definition,
                "revocable": False,
                "supports_ref_uid": False,
                "anchor_scope": "PUBLIC_EVM_ATTESTATION_CHECKPOINT_HASH_ONLY",
            }
        if normalized == "COUNTERPARTY_ATTESTATION":
            if not self.coattestation_schema_uid:
                raise RuntimeError("EAS_COATTESTATION_SCHEMA_NOT_CONFIGURED")
            return {
                "commitment_type": "COUNTERPARTY_ATTESTATION",
                "schema_uid": self.coattestation_schema_uid,
                "schema_definition": self.coattestation_schema_definition,
                # A counterparty can withdraw its commitment, so this attestation
                # must be revocable; an evidence checkpoint must not be.
                "revocable": True,
                # refUID is what makes this a second opinion about the same packet
                # rather than an unrelated attestation that merely looks similar.
                "supports_ref_uid": True,
                "anchor_scope": "PUBLIC_EVM_ATTESTATION_COUNTERPARTY_HASH_ONLY",
            }
        raise ValueError("Unsupported EAS commitment type")

    @staticmethod
    def _policy_ref_uid(policy: dict, context: object | None) -> str | None:
        """Read the referenced attestation UID a commitment type is allowed to bind."""
        if not policy.get("supports_ref_uid") or not isinstance(context, dict):
            return None
        value = context.get("ref_uid")
        if value in (None, "", _canonical_bytes32(_ZERO_BYTES32)):
            return None
        return _canonical_bytes32(value)

    def _environment_status(self, web3) -> dict:
        connected = bool(web3.is_connected())
        if not connected:
            return {"ready": False, "reason": "EAS_RPC_NOT_CONNECTED", "rpc_connected": False}
        live_chain_id = int(web3.eth.chain_id)
        chain_matches = self.chain_id is None or live_chain_id == self.chain_id
        contract_status = self._contract_code_status(web3, self.contract_address)
        contract_ok = (
            contract_status["has_code"] and contract_status["code_matches_expected"] is not False
        )
        schema_status: dict = {}
        checkpoint_schema_status: dict = {}
        coattestation_schema_status: dict = {}
        if contract_ok and chain_matches:
            contract = self._contract(web3)
            schema_status = self._schema_status(
                web3,
                contract,
                schema_uid=self.schema_uid,
                schema_definition=self.schema_definition,
                expected_revocable=True,
            )
            if self.checkpoint_schema_uid:
                checkpoint_schema_status = self._schema_status(
                    web3,
                    contract,
                    schema_uid=self.checkpoint_schema_uid,
                    schema_definition=self.checkpoint_schema_definition,
                    expected_revocable=False,
                )
            if self.coattestation_schema_uid:
                coattestation_schema_status = self._schema_status(
                    web3,
                    contract,
                    schema_uid=self.coattestation_schema_uid,
                    schema_definition=self.coattestation_schema_definition,
                    expected_revocable=True,
                )

        def schema_ready(status: dict) -> bool:
            return bool(
                status.get("schema_registry_has_code")
                and status.get("schema_registered")
                and status.get("schema_definition_matches")
                and status.get("schema_revocability_matches")
            )

        schema_ok = schema_ready(schema_status)
        checkpoint_schema_ok = not self.checkpoint_schema_uid or schema_ready(
            checkpoint_schema_status
        )
        coattestation_schema_ok = not self.coattestation_schema_uid or schema_ready(
            coattestation_schema_status
        )
        reason = None
        if not chain_matches:
            reason = "EAS_CHAIN_ID_MISMATCH"
        elif not contract_status["has_code"]:
            reason = "EAS_CONTRACT_HAS_NO_CODE"
        elif contract_status["code_matches_expected"] is False:
            reason = "EAS_CONTRACT_CODE_HASH_MISMATCH"
        elif not schema_ok or not checkpoint_schema_ok or not coattestation_schema_ok:
            reason = "EAS_SCHEMA_VALIDATION_FAILED"
        return {
            "ready": reason is None,
            "reason": reason,
            "rpc_connected": connected,
            "chain_id": live_chain_id,
            "configured_chain_id": self.chain_id,
            "chain_id_matches": chain_matches,
            "contract_address": self.contract_address,
            **contract_status,
            **schema_status,
            "checkpoint_schema": checkpoint_schema_status or None,
            "coattestation_schema": coattestation_schema_status or None,
        }

    def _finality_tag_status(self, web3) -> dict:
        """Fail closed when the configured protocol-finality tag is unavailable."""
        tag = self.finality_policy if self.finality_policy in {"safe", "finalized"} else None
        if tag is None:
            return {
                "configured_finality_tag": None,
                "finality_tag_supported": True,
                "finality_tag_block_number": None,
                "reason": None,
            }
        try:
            block = web3.eth.get_block(tag)
            number = _field(block, "number", 0, None)
            if number is None or isinstance(number, bool) or int(number) < 0:
                raise ValueError("finality tag block has no valid number")
            return {
                "configured_finality_tag": tag,
                "finality_tag_supported": True,
                "finality_tag_block_number": int(number),
                "reason": None,
            }
        except Exception:
            return {
                "configured_finality_tag": tag,
                "finality_tag_supported": False,
                "finality_tag_block_number": None,
                "reason": f"EAS_{tag.upper()}_BLOCK_TAG_UNAVAILABLE",
            }

    def _remember_preflight(self, result: dict) -> dict:
        checked_at = datetime.now(UTC).isoformat()
        payload = {**result, "checked_at": checked_at}
        self._last_preflight = payload
        self._last_preflight_at = checked_at
        self._last_preflight_monotonic = time.monotonic()
        return payload

    def _refresh_preflight_cache(self) -> None:
        """Populate live readiness on first status call and refresh it on a short TTL."""
        if not self.available or self._web3 is None:
            return
        last_checked = getattr(self, "_last_preflight_monotonic", None)
        if (
            last_checked is not None
            and time.monotonic() - last_checked < self._preflight_status_ttl_seconds
        ):
            return
        lock = getattr(self, "_preflight_lock", None)
        if lock is None:  # Supports narrow object.__new__ test doubles.
            lock = threading.Lock()
            self._preflight_lock = lock
        with lock:
            last_checked = getattr(self, "_last_preflight_monotonic", None)
            if (
                last_checked is None
                or time.monotonic() - last_checked >= self._preflight_status_ttl_seconds
            ):
                self.preflight()

    def _fee_fields(self, web3) -> tuple[dict, int]:
        latest = web3.eth.get_block("latest")
        base_fee = _field(latest, "baseFeePerGas", 0, None)
        if base_fee is not None:
            base_fee = int(base_fee)
            try:
                priority_fee = int(web3.eth.max_priority_fee)
            except Exception:
                priority_fee = min(int(web3.eth.gas_price), 2_000_000_000)
            priority_fee = max(0, priority_fee)
            minimum = base_fee + priority_fee
            if self.max_fee_per_gas_wei and minimum > self.max_fee_per_gas_wei:
                raise RuntimeError("EAS_MAX_FEE_CAP_BELOW_CURRENT_BASE_FEE")
            max_fee = (2 * base_fee) + priority_fee
            if self.max_fee_per_gas_wei:
                max_fee = min(max_fee, self.max_fee_per_gas_wei)
                priority_fee = min(priority_fee, max(0, max_fee - base_fee))
            return {
                "maxFeePerGas": max_fee,
                "maxPriorityFeePerGas": priority_fee,
            }, max_fee
        gas_price = int(web3.eth.gas_price)
        if self.max_fee_per_gas_wei and gas_price > self.max_fee_per_gas_wei:
            raise RuntimeError("EAS_GAS_PRICE_ABOVE_CAP")
        return {"gasPrice": gas_price}, gas_price

    def _parse_attestation(self, raw: object) -> dict:
        data = bytes(_field(raw, "data", 9, b""))
        commitment = data.hex() if len(data) == 32 else None
        return {
            "uid": _canonical_bytes32(_field(raw, "uid", 0, _ZERO_BYTES32)),
            "schema_uid": _canonical_bytes32(_field(raw, "schema", 1, _ZERO_BYTES32)),
            "time": int(_field(raw, "time", 2, 0) or 0),
            "expiration_time": int(_field(raw, "expirationTime", 3, 0) or 0),
            "revocation_time": int(_field(raw, "revocationTime", 4, 0) or 0),
            "ref_uid": _canonical_bytes32(_field(raw, "refUID", 5, _ZERO_BYTES32)),
            "recipient": str(_field(raw, "recipient", 6, "")),
            "attester": str(_field(raw, "attester", 7, "")),
            "revocable": bool(_field(raw, "revocable", 8, False)),
            "data_length": len(data),
            "packet_hash_sha256": commitment,
        }

    def _verify_attestation(
        self,
        web3,
        contract,
        *,
        attestation_uid: str,
        expected_packet_hash: str | None,
        expected_metadata: dict | None = None,
    ) -> dict:
        metadata = expected_metadata or {}
        policy = self._commitment_policy(metadata.get("commitment_type"))
        uid = _canonical_bytes32(attestation_uid)
        expected_hash = (
            _canonical_packet_hash(expected_packet_hash)
            if expected_packet_hash is not None
            else None
        )
        live_chain_id = int(web3.eth.chain_id)
        expected_chain_id = metadata.get("chain_id", self.chain_id)
        expected_schema = _canonical_bytes32(metadata.get("schema_uid", policy["schema_uid"]))
        expected_attester = metadata.get(
            "attester_address", self.required_attester_address or self.attester_address
        )
        expected_recipient = metadata.get("recipient", self.recipient)
        expected_contract = metadata.get("contract_address", self.contract_address)
        expected_revocable = bool(metadata.get("revocable", policy["revocable"]))
        expected_ref_uid = self._policy_ref_uid(policy, metadata)
        raw = contract.functions.getAttestation(_bytes32(uid)).call()
        attestation = self._parse_attestation(raw)
        contract_valid = bool(contract.functions.isAttestationValid(_bytes32(uid)).call())
        try:
            latest = web3.eth.get_block("latest")
            chain_time = int(_field(latest, "timestamp", 0, time.time()) or time.time())
        except Exception:
            chain_time = int(time.time())
        expiration = attestation["expiration_time"]
        checks = {
            "contract_reported_valid": contract_valid,
            "uid_matches": attestation["uid"] == uid and uid != _canonical_bytes32(_ZERO_BYTES32),
            "schema_matches_expected": attestation["schema_uid"] == expected_schema,
            "attester_matches_expected": _address_equal(attestation["attester"], expected_attester),
            "recipient_matches_expected": _address_equal(
                attestation["recipient"], expected_recipient
            ),
            "chain_id_matches_expected": (
                expected_chain_id is None or live_chain_id == int(expected_chain_id)
            ),
            "contract_address_matches_expected": _address_equal(
                self.contract_address, expected_contract
            ),
            "commitment_decodes_as_bytes32": attestation["data_length"] == 32,
            "commitment_matches_expected": (
                None
                if expected_hash is None
                else attestation["packet_hash_sha256"] == expected_hash
            ),
            "not_revoked": attestation["revocation_time"] == 0,
            "not_expired": expiration == 0 or expiration > chain_time,
            "created_on_chain": attestation["time"] > 0,
            "revocability_matches_expected": (attestation["revocable"] == expected_revocable),
        }
        if expected_ref_uid is None:
            # Packet and checkpoint commitments stand alone; a populated refUID
            # would mean this attestation is part of a chain we did not build.
            checks["ref_uid_is_zero"] = attestation["ref_uid"] == _canonical_bytes32(_ZERO_BYTES32)
        else:
            # A counterparty commitment is only meaningful while it points at the
            # platform attestation for the same evidence packet.
            checks["ref_uid_matches_expected"] = attestation["ref_uid"] == expected_ref_uid
        required_checks = [value for value in checks.values() if value is not None]
        valid = all(required_checks)
        reason_codes = [name.upper() for name, value in checks.items() if value is False]
        return {
            "checked": True,
            "attestation_uid": uid,
            "attestation_valid": valid,
            "chain_id": live_chain_id,
            "commitment_type": policy["commitment_type"],
            "contract_address": self.contract_address,
            "schema_uid": attestation["schema_uid"],
            "attester_address": attestation["attester"],
            "recipient": attestation["recipient"],
            "commitment_hash_sha256": attestation["packet_hash_sha256"],
            **_commitment_hash_alias(policy["commitment_type"], attestation["packet_hash_sha256"]),
            "ref_uid": attestation["ref_uid"],
            "expected_ref_uid": expected_ref_uid,
            "attestation_time": attestation["time"],
            "expiration_time": expiration,
            "revocation_time": attestation["revocation_time"],
            "chain_time": chain_time,
            "checks": checks,
            "reason_codes": reason_codes,
            "binding_matches": (
                valid and checks["commitment_matches_expected"] is True
                if expected_hash is not None
                else None
            ),
            "finalized": False,
        }

    def _event_uid(self, contract, mined, *, expected_metadata: dict | None = None) -> str | None:
        metadata = expected_metadata or {}
        policy = self._commitment_policy(metadata.get("commitment_type"))
        expected_uid = metadata.get("attestation_uid")
        for event in contract.events.Attested().process_receipt(mined):
            if not _address_equal(event.get("address"), self.contract_address):
                continue
            args = event["args"]
            try:
                uid = _canonical_bytes32(args["uid"])
                schema = _canonical_bytes32(args["schemaUID"])
            except (KeyError, TypeError, ValueError):
                continue
            if schema != _canonical_bytes32(metadata.get("schema_uid", policy["schema_uid"])):
                continue
            if not _address_equal(
                args.get("attester"),
                metadata.get(
                    "attester_address", self.required_attester_address or self.attester_address
                ),
            ):
                continue
            if not _address_equal(args.get("recipient"), metadata.get("recipient", self.recipient)):
                continue
            if expected_uid and uid != _canonical_bytes32(expected_uid):
                continue
            return uid
        return None

    def _confirmation_status(self, web3, mined, tx_hex: str) -> dict:
        original_block_hash = _canonical_bytes32(_field(mined, "blockHash", 0, _ZERO_BYTES32))
        block_number = int(_field(mined, "blockNumber", 0, 0) or 0)
        confirmations = 0
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            confirmations = max(0, int(web3.eth.block_number) - block_number + 1)
            if confirmations >= self.required_confirmations or time.monotonic() >= deadline:
                break
            time.sleep(1)
        latest_receipt = web3.eth.get_transaction_receipt(tx_hex)
        latest_block_hash = _canonical_bytes32(
            _field(latest_receipt, "blockHash", 0, _ZERO_BYTES32)
        )
        latest_block_number = int(_field(latest_receipt, "blockNumber", 0, 0) or 0)
        receipt_transaction_hash = _canonical_bytes32(
            _field(latest_receipt, "transactionHash", 0, _ZERO_BYTES32)
        )
        canonical_block = web3.eth.get_block(block_number)
        canonical_block_hash = _canonical_bytes32(_field(canonical_block, "hash", 0, _ZERO_BYTES32))
        transaction = web3.eth.get_transaction(tx_hex)
        transaction_hash = _canonical_bytes32(_field(transaction, "hash", 0, _ZERO_BYTES32))
        transaction_to = str(_field(transaction, "to", 0, ""))
        transaction_from = str(_field(transaction, "from", 0, ""))
        canonical = (
            original_block_hash == latest_block_hash == canonical_block_hash
            and original_block_hash != _canonical_bytes32(_ZERO_BYTES32)
            and latest_block_number == block_number
            and receipt_transaction_hash == transaction_hash == _canonical_bytes32(tx_hex)
            and _address_equal(transaction_to, self.contract_address)
            and _address_equal(
                transaction_from,
                self.required_attester_address or self.attester_address,
            )
        )

        def tagged_block_contains(tag: str) -> bool | None:
            try:
                tagged = web3.eth.get_block(tag)
                tagged_number = _field(tagged, "number", 0, None)
                if tagged_number is None:
                    return None
                return bool(canonical and int(tagged_number) >= block_number)
            except Exception:
                # Some EVM RPC providers do not expose the safe/finalized tags.
                # Unknown is materially different from false or depth-confirmed.
                return None

        expected_block_hash = None
        return {
            "block_number": block_number,
            "block_hash": original_block_hash,
            "confirmations": confirmations,
            "required_confirmations": self.required_confirmations,
            "confirmation_depth_reached": confirmations >= self.required_confirmations,
            "safe_block_verified": tagged_block_contains("safe"),
            "finalized_block_verified": tagged_block_contains("finalized"),
            "canonical_receipt": canonical,
            "transaction_target_matches": _address_equal(transaction_to, self.contract_address),
            "transaction_sender_matches": _address_equal(
                transaction_from,
                self.required_attester_address or self.attester_address,
            ),
            "expected_block_hash": expected_block_hash,
            "latest_receipt": latest_receipt,
        }

    def _finalize_transaction(
        self,
        web3,
        *,
        tx_hex: str,
        packet_hash: str,
        fee_basis_wei: int = 0,
        commitment_type: str = "CANONICAL_EVIDENCE_PACKET_SHA256",
        started: float | None = None,
        expected_metadata: dict | None = None,
    ) -> dict:
        policy = self._commitment_policy(commitment_type)
        metadata = {
            "commitment_type": policy["commitment_type"],
            "schema_uid": policy["schema_uid"],
            "finality_policy": self.finality_policy,
            "revocable": policy["revocable"],
            **(expected_metadata or {}),
        }
        mined = web3.eth.wait_for_transaction_receipt(
            tx_hex, timeout=self.timeout_seconds, poll_latency=1
        )
        contract = self._contract(web3)
        uid = self._event_uid(contract, mined, expected_metadata=metadata)
        confirmation = self._confirmation_status(web3, mined, tx_hex)
        if metadata.get("block_hash"):
            expected_block_hash = _canonical_bytes32(metadata["block_hash"])
            confirmation["expected_block_hash"] = expected_block_hash
            confirmation["canonical_receipt"] = bool(
                confirmation["canonical_receipt"]
                and confirmation["block_hash"] == expected_block_hash
            )
        if metadata.get("block_number") is not None:
            expected_block_number = int(metadata["block_number"])
            confirmation["expected_block_number"] = expected_block_number
            confirmation["canonical_receipt"] = bool(
                confirmation["canonical_receipt"]
                and confirmation["block_number"] == expected_block_number
            )
        verification = (
            self._verify_attestation(
                web3,
                contract,
                attestation_uid=uid,
                expected_packet_hash=packet_hash,
                expected_metadata=metadata,
            )
            if uid
            else {
                "checked": True,
                "attestation_valid": False,
                "reason_codes": ["MATCHING_ATTESTED_EVENT_NOT_FOUND"],
            }
        )
        latest_receipt = confirmation.pop("latest_receipt")
        gas_used = int(_field(latest_receipt, "gasUsed", 0, 0) or 0)
        effective_gas_price = int(
            _field(latest_receipt, "effectiveGasPrice", 0, fee_basis_wei) or fee_basis_wei
        )
        transaction_status = int(_field(latest_receipt, "status", 0, 0) or 0)
        chain_id = int(web3.eth.chain_id)
        receipt = {
            "schema": "creatorproof.eas_receipt.v3",
            "commitment_hash_sha256": packet_hash,
            **_commitment_hash_alias(policy["commitment_type"], packet_hash),
            "commitment_type": policy["commitment_type"],
            "ref_uid": self._policy_ref_uid(policy, metadata),
            "committed_value": policy["schema_definition"],
            "network_label": self.network_label or None,
            "chain_id": chain_id,
            "contract_address": self.contract_address,
            "schema_uid": policy["schema_uid"],
            "attester_address": self.required_attester_address or self.attester_address,
            "recipient": self.recipient,
            "transaction_hash": tx_hex,
            **{key: value for key, value in confirmation.items()},
            "transaction_status": transaction_status,
            "gas_used": gas_used,
            "effective_gas_price_wei": effective_gas_price,
            "fee_wei": gas_used * effective_gas_price,
            "attestation_uid": uid,
            "attestation_valid": bool(verification["attestation_valid"]),
            "attestation_verification": verification,
            "revocable": policy["revocable"],
            "confirmation_latency_ms": (
                round((time.monotonic() - started) * 1000.0, 3) if started is not None else None
            ),
            "anchored_at": datetime.now(UTC).isoformat(),
            "explorer": self._explorer_urls(tx_hex, uid),
            "anchor_scope": policy["anchor_scope"],
            "privacy_note": _PRIVACY_NOTES.get(
                policy["commitment_type"], _PRIVACY_NOTES["EVIDENCE_PACKET"]
            ),
            "trust_note": _TRUST_NOTES.get(
                policy["commitment_type"], _TRUST_NOTES["EVIDENCE_PACKET"]
            ),
        }
        receipt["anchor_conditions_met"] = self._receipt_is_anchored(receipt)
        receipt["finalized"] = bool(
            receipt["anchor_conditions_met"] and receipt.get("finalized_block_verified") is True
        )
        receipt["proof_kind"] = policy["commitment_type"]
        receipt["explorer_urls"] = receipt["explorer"]
        return receipt

    def _idempotency_key(
        self,
        chain_id: int,
        packet_hash: str,
        commitment_type: str,
        ref_uid: str | None = None,
    ) -> str:
        policy = self._commitment_policy(commitment_type)
        material = "|".join(
            (
                str(chain_id),
                self.contract_address.lower(),
                policy["schema_uid"].lower(),
                self.recipient.lower(),
                (self.required_attester_address or self.attester_address or "").lower(),
                packet_hash,
                commitment_type,
                # Two attestations of the same body under different references are
                # different transactions and must not reuse one prepared nonce.
                (ref_uid or "").lower(),
            )
        )
        return hashlib.sha256(material.encode()).hexdigest()

    def _prepare_and_broadcast(
        self,
        web3,
        *,
        packet_hash: str,
        commitment_type: str,
        context: object | None,
        on_transaction_prepared,
        notify_callback: bool,
    ) -> dict:
        policy = self._commitment_policy(commitment_type)
        account = web3.eth.account.from_key(self.private_key)
        live_chain_id = int(web3.eth.chain_id)
        if self.chain_id is not None and live_chain_id != self.chain_id:
            raise RuntimeError("EAS_CHAIN_ID_MISMATCH")
        chain_id = self.chain_id or live_chain_id
        contract = self._contract(web3)
        ref_uid = self._policy_ref_uid(policy, context)
        request = (
            _bytes32(policy["schema_uid"]),
            (
                self._web3.to_checksum_address(self.recipient),
                0,
                policy["revocable"],
                _bytes32(ref_uid) if ref_uid else _ZERO_BYTES32,
                bytes.fromhex(packet_hash),
                0,
            ),
        )
        cache_key = self._idempotency_key(chain_id, packet_hash, policy["commitment_type"], ref_uid)
        with self._nonce_lock:
            prepared = self._prepared_transactions.get(cache_key)
            if prepared is None:
                environment = self._environment_status(web3)
                if not environment["ready"]:
                    raise RuntimeError(environment["reason"] or "EAS_PREFLIGHT_FAILED")
                fee_fields, fee_basis = self._fee_fields(web3)
                nonce = int(web3.eth.get_transaction_count(account.address, "pending"))
                transaction = contract.functions.attest(request).build_transaction(
                    {
                        "from": account.address,
                        "nonce": nonce,
                        "chainId": chain_id,
                        "value": 0,
                        **fee_fields,
                    }
                )
                estimate = web3.eth.estimate_gas(transaction)
                transaction["gas"] = max(100_000, math.ceil(estimate * 1.2))
                signed = account.sign_transaction(transaction)
                raw_transaction = bytes(
                    getattr(signed, "raw_transaction", getattr(signed, "rawTransaction", b""))
                )
                if not raw_transaction:
                    raise RuntimeError("EAS_SIGNED_TRANSACTION_EMPTY")
                signed_hash = getattr(signed, "hash", None)
                tx_hex = (
                    _canonical_bytes32(signed_hash)
                    if signed_hash is not None
                    else _canonical_bytes32(web3.keccak(raw_transaction))
                )
                prepared = {
                    "tx_hash": tx_hex,
                    "raw_transaction": raw_transaction,
                    "nonce": nonce,
                    "chain_id": chain_id,
                    "fee_basis_wei": fee_basis,
                    "ref_uid": ref_uid,
                }
                callback_payload = {
                    "transaction_hash": tx_hex,
                    "tx_hash": tx_hex,
                    "nonce": nonce,
                    "chain_id": chain_id,
                    "signed_transaction_hex": f"0x{raw_transaction.hex()}",
                    "commitment_hash_sha256": packet_hash,
                    **_commitment_hash_alias(policy["commitment_type"], packet_hash),
                    "commitment_type": policy["commitment_type"],
                    "ref_uid": ref_uid,
                    "context": context,
                }
                if on_transaction_prepared is not None and notify_callback:
                    # The signed transaction is crash-recovery material; no private
                    # key or unsigned secret is exposed.
                    on_transaction_prepared(callback_payload)
                self._prepared_transactions[cache_key] = prepared
                if len(self._prepared_transactions) > self._prepared_cache_limit:
                    oldest = next(iter(self._prepared_transactions))
                    self._prepared_transactions.pop(oldest, None)
            elif on_transaction_prepared is not None and notify_callback:
                on_transaction_prepared(
                    {
                        "transaction_hash": prepared["tx_hash"],
                        "tx_hash": prepared["tx_hash"],
                        "nonce": prepared["nonce"],
                        "chain_id": prepared["chain_id"],
                        "signed_transaction_hex": (f"0x{prepared['raw_transaction'].hex()}"),
                        "commitment_hash_sha256": packet_hash,
                        **_commitment_hash_alias(policy["commitment_type"], packet_hash),
                        "commitment_type": policy["commitment_type"],
                        "ref_uid": ref_uid,
                        "context": context,
                    }
                )
            try:
                returned_hash = web3.eth.send_raw_transaction(prepared["raw_transaction"])
                if _canonical_bytes32(returned_hash) != prepared["tx_hash"]:
                    raise RuntimeError("EAS_BROADCAST_HASH_MISMATCH")
            except Exception as exc:
                if not _is_transient_chain_error(exc):
                    raise
                # A timeout or "already known" can mean the exact signed transaction
                # reached the node. Confirmation by its deterministic hash is safe.
                logger.warning(
                    "eas_broadcast_outcome_unknown tx=%s error=%s",
                    prepared["tx_hash"],
                    type(exc).__name__,
                )
        return prepared

    def broadcast_signed_transaction(
        self, signed_transaction_hex: str, expected_transaction_hash: str
    ) -> dict:
        """Broadcast an exactly persisted signed transaction after a worker crash.

        Signed transaction bytes are safe to persist as an outbox payload: they do
        not contain the private key and are bound to their chain id and nonce. This
        method never logs or returns the raw bytes.
        """
        if not self.available or self._web3 is None:
            return {"broadcast": False, "reason": self.unavailable_reason or "EAS_UNAVAILABLE"}
        try:
            if not isinstance(signed_transaction_hex, str):
                raise ValueError("signed transaction must be hex")
            raw_transaction = bytes.fromhex(signed_transaction_hex.removeprefix("0x"))
            if not raw_transaction:
                raise ValueError("signed transaction cannot be empty")
            expected_hash = _canonical_bytes32(expected_transaction_hash)
            web3 = self._connect()
            actual_hash = _canonical_bytes32(web3.keccak(raw_transaction))
            if actual_hash != expected_hash:
                return {"broadcast": False, "reason": "SIGNED_TRANSACTION_HASH_MISMATCH"}
            environment = self._environment_status(web3)
            if not environment["ready"]:
                return {"broadcast": False, "reason": environment["reason"]}
            try:
                returned_hash = _canonical_bytes32(web3.eth.send_raw_transaction(raw_transaction))
                if returned_hash != expected_hash:
                    return {"broadcast": False, "reason": "EAS_BROADCAST_HASH_MISMATCH"}
            except Exception as exc:
                if not _is_transient_chain_error(exc):
                    raise
                # "already known" and a post-send timeout both preserve the exact hash.
            return {"broadcast": True, "transaction_hash": expected_hash, "reason": None}
        except (TypeError, ValueError):
            return {"broadcast": False, "reason": "INVALID_SIGNED_TRANSACTION"}
        except Exception as exc:
            return {"broadcast": False, "reason": f"EAS_BROADCAST_FAILED:{type(exc).__name__}"}

    def _submit_once(
        self,
        packet_hash: str,
        *,
        context: object | None = None,
        commitment_type: str = "CANONICAL_EVIDENCE_PACKET_SHA256",
        on_transaction_prepared=None,
        notify_callback: bool = True,
    ) -> dict:
        started = time.monotonic()
        web3 = self._connect()
        prepared = self._prepare_and_broadcast(
            web3,
            packet_hash=packet_hash,
            commitment_type=commitment_type,
            context=context,
            on_transaction_prepared=on_transaction_prepared,
            notify_callback=notify_callback,
        )
        return self._finalize_transaction(
            web3,
            tx_hex=prepared["tx_hash"],
            packet_hash=packet_hash,
            fee_basis_wei=prepared["fee_basis_wei"],
            commitment_type=commitment_type,
            started=started,
            # The reference bound into the transaction must also be what the
            # read-back is checked against, not merely what we intended to send.
            expected_metadata=(
                {"ref_uid": prepared["ref_uid"]} if prepared.get("ref_uid") else None
            ),
        )

    def _receipt_is_anchored(self, receipt: dict) -> bool:
        depth_reached = receipt.get("confirmation_depth_reached")
        if depth_reached is None:
            # Compatibility for persisted v3 receipts and narrow test doubles.
            depth_reached = receipt.get("finality_reached")
        base_conditions_met = bool(
            receipt.get("transaction_status") == 1
            and receipt.get("attestation_valid") is True
            and receipt.get("canonical_receipt") is True
            and int(receipt.get("confirmations", 0)) >= self.required_confirmations
            and depth_reached is True
        )
        if not base_conditions_met:
            return False
        if self.finality_policy == "safe":
            return receipt.get("safe_block_verified") is True
        if self.finality_policy == "finalized":
            return receipt.get("finalized_block_verified") is True
        return True

    def _receipt_status(self, receipt: dict) -> AnchorStatus:
        if self._receipt_is_anchored(receipt):
            return AnchorStatus.ANCHORED
        if (
            receipt.get("transaction_status") == 1
            and receipt.get("attestation_valid") is True
            and receipt.get("canonical_receipt") is True
        ):
            return AnchorStatus.PENDING
        return AnchorStatus.FAILED

    def _failure_scope(self, commitment_type: str | None) -> str:
        """Describe what would have been committed, even when nothing was."""
        try:
            return str(self._commitment_policy(commitment_type)["anchor_scope"])
        except (RuntimeError, ValueError):
            return "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY"

    def anchor(
        self,
        packet_hash: str,
        *,
        context: object | None = None,
        commitment_type: str | None = None,
        on_transaction_prepared=None,
    ) -> ProofReceipt:
        failure_scope = self._failure_scope(commitment_type)
        if not self.available or self._web3 is None:
            return ProofReceipt(
                status=AnchorStatus.FAILED,
                provider=self.name,
                receipt={
                    "error_code": self.unavailable_reason or "EAS_UNAVAILABLE",
                    "anchor_scope": failure_scope,
                },
            )
        try:
            normalized_hash = _canonical_packet_hash(packet_hash)
        except (TypeError, ValueError):
            return ProofReceipt(
                status=AnchorStatus.FAILED,
                provider=self.name,
                receipt={
                    "error_code": "INVALID_PACKET_HASH",
                    "anchor_scope": failure_scope,
                },
            )
        commitment_type = commitment_type or "CANONICAL_EVIDENCE_PACKET_SHA256"
        attempts: list[dict] = []
        for attempt in range(1, self.max_attempts + 1):
            try:
                receipt = self._submit_once(
                    normalized_hash,
                    context=context,
                    commitment_type=commitment_type,
                    on_transaction_prepared=on_transaction_prepared,
                    notify_callback=attempt == 1,
                )
                receipt["attempts"] = attempt
                receipt["attempt_log"] = attempts
                receipt["anchor_conditions_met"] = self._receipt_is_anchored(receipt)
                receipt["finalized"] = bool(
                    receipt["anchor_conditions_met"]
                    and receipt.get("finalized_block_verified") is True
                )
                return ProofReceipt(
                    status=self._receipt_status(receipt),
                    provider=self.name,
                    receipt=receipt,
                )
            except Exception as exc:
                transient = _is_transient_chain_error(exc)
                attempts.append(
                    {
                        "attempt": attempt,
                        "error_code": f"EAS_ANCHOR_FAILED:{type(exc).__name__}",
                        "retry_class": "TRANSIENT" if transient else "TERMINAL",
                    }
                )
                logger.warning(
                    "eas_anchor_attempt_failed attempt=%s transient=%s error=%s",
                    attempt,
                    transient,
                    type(exc).__name__,
                )
                if not transient or attempt == self.max_attempts:
                    return ProofReceipt(
                        status=AnchorStatus.FAILED,
                        provider=self.name,
                        receipt={
                            "error_code": f"EAS_ANCHOR_FAILED:{type(exc).__name__}",
                            "attempts": attempt,
                            "attempt_log": attempts,
                            "anchor_scope": failure_scope,
                            "impact_note": (
                                "Proof anchoring failed. The evidence result and policy "
                                "action are unchanged and remain locally verifiable."
                            ),
                        },
                    )
                time.sleep(self.retry_backoff_seconds * attempt)
        return ProofReceipt(  # pragma: no cover - loop always returns
            status=AnchorStatus.FAILED,
            provider=self.name,
            receipt={"error_code": "EAS_ANCHOR_EXHAUSTED"},
        )

    def verify(
        self,
        *,
        attestation_uid: str,
        expected_packet_hash: str | None = None,
        expected_commitment_hash: str | None = None,
        expected_metadata: dict | None = None,
    ) -> dict:
        """Read and bind every security-relevant EAS field to local expectations.

        UID-only callers remain supported. They receive the decoded commitment and
        all configured-identity checks, while ``commitment_matches_expected`` is
        explicitly ``None`` until the caller supplies the packet/commitment hash.
        """
        if not self.available or self._web3 is None:
            return {"checked": False, "reason": self.unavailable_reason or "EAS_UNAVAILABLE"}
        try:
            if (
                expected_packet_hash is not None
                and expected_commitment_hash is not None
                and _canonical_packet_hash(expected_packet_hash)
                != _canonical_packet_hash(expected_commitment_hash)
            ):
                return {
                    "checked": False,
                    "reason": "CONFLICTING_EXPECTED_COMMITMENT_HASHES",
                }
            expected_hash = expected_packet_hash or expected_commitment_hash
            web3 = self._connect()
            environment = self._environment_status(web3)
            if not environment["ready"]:
                return {
                    "checked": False,
                    "reason": environment["reason"],
                    "chain_id": environment.get("chain_id"),
                    "contract_address": self.contract_address,
                }
            return self._verify_attestation(
                web3,
                self._contract(web3),
                attestation_uid=attestation_uid,
                expected_packet_hash=expected_hash,
                expected_metadata=expected_metadata,
            )
        except (TypeError, ValueError):
            return {"checked": False, "reason": "EAS_VERIFY_INVALID_INPUT"}
        except Exception as exc:
            return {"checked": False, "reason": f"EAS_VERIFY_FAILED:{type(exc).__name__}"}

    def reconcile(
        self,
        transaction_hash: str,
        expected_commitment_hash: str,
        expected_metadata: dict | None = None,
        signed_transaction_hex: str | None = None,
    ) -> ProofReceipt:
        """Resume a prepared/broadcast transaction without creating a new nonce."""
        if not self.available or self._web3 is None:
            return ProofReceipt(
                status=AnchorStatus.FAILED,
                provider=self.name,
                receipt={"error_code": self.unavailable_reason or "EAS_UNAVAILABLE"},
            )
        try:
            tx_hex = _canonical_bytes32(transaction_hash)
            packet_hash = _canonical_packet_hash(expected_commitment_hash)
            web3 = self._connect()
            environment = self._environment_status(web3)
            if not environment["ready"]:
                raise RuntimeError(environment["reason"] or "EAS_PREFLIGHT_FAILED")
            if signed_transaction_hex:
                broadcast = self.broadcast_signed_transaction(signed_transaction_hex, tx_hex)
                if not broadcast["broadcast"]:
                    raise RuntimeError(broadcast["reason"] or "EAS_REBROADCAST_FAILED")
            receipt = self._finalize_transaction(
                web3,
                tx_hex=tx_hex,
                packet_hash=packet_hash,
                commitment_type=str(
                    (expected_metadata or {}).get(
                        "commitment_type", "CANONICAL_EVIDENCE_PACKET_SHA256"
                    )
                ),
                expected_metadata=expected_metadata,
            )
            receipt["reconciled"] = True
            receipt["anchor_conditions_met"] = self._receipt_is_anchored(receipt)
            receipt["finalized"] = bool(
                receipt["anchor_conditions_met"] and receipt.get("finalized_block_verified") is True
            )
            return ProofReceipt(
                status=self._receipt_status(receipt),
                provider=self.name,
                receipt=receipt,
            )
        except (TypeError, ValueError):
            error_code = "EAS_RECONCILE_INVALID_INPUT"
        except Exception as exc:
            error_code = f"EAS_RECONCILE_FAILED:{type(exc).__name__}"
        return ProofReceipt(
            status=AnchorStatus.FAILED,
            provider=self.name,
            receipt={
                "error_code": error_code,
                "transaction_hash": transaction_hash,
                "anchor_scope": "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
            },
        )

    def preflight(self) -> dict:
        """Validate RPC, chain, bytecode, schema, signer funds and fee policy."""
        if not self.available or self._web3 is None:
            return self._remember_preflight(
                {"ready": False, "reason": self.unavailable_reason or "EAS_UNAVAILABLE"}
            )
        try:
            web3 = self._connect()
            environment = self._environment_status(web3)
            if not environment["ready"]:
                return self._remember_preflight(
                    {**environment, "network_label": self.network_label or None}
                )
            finality_tag = self._finality_tag_status(web3)
            if not finality_tag["finality_tag_supported"]:
                return self._remember_preflight(
                    {
                        **environment,
                        **finality_tag,
                        "ready": False,
                        "network_label": self.network_label or None,
                    }
                )
            balance_wei = int(web3.eth.get_balance(self.attester_address))
            fee_fields, fee_basis = self._fee_fields(web3)
            ready = balance_wei > 0
            return self._remember_preflight(
                {
                    **environment,
                    **finality_tag,
                    "ready": ready,
                    "network_label": self.network_label or None,
                    "attester_address": self.attester_address,
                    "attester_balance_wei": balance_wei,
                    "fee_model": "EIP_1559" if "maxFeePerGas" in fee_fields else "LEGACY",
                    "maximum_transaction_fee_per_gas_wei": fee_basis,
                    "reason": None if ready else "ATTESTER_BALANCE_EMPTY",
                }
            )
        except Exception as exc:
            return self._remember_preflight(
                {"ready": False, "reason": f"EAS_PREFLIGHT_FAILED:{type(exc).__name__}"}
            )

    def status(self) -> dict:
        self._refresh_preflight_cache()
        last_preflight = getattr(self, "_last_preflight", None)
        if self.available:
            live_write_ready = (
                bool(last_preflight.get("ready")) if last_preflight is not None else None
            )
            live_write_reason = (
                last_preflight.get("reason")
                if last_preflight is not None
                else "EAS_PREFLIGHT_NOT_RUN"
            )
        else:
            live_write_ready = False
            live_write_reason = self.unavailable_reason or "EAS_UNAVAILABLE"
        return {
            "provider": self.name,
            "available": self.available,
            "configured": self.available,
            "live_write_ready": live_write_ready,
            "live_write_reason": live_write_reason,
            "live_write_checked_at": getattr(self, "_last_preflight_at", None),
            "is_blockchain": True,
            "scope": "PUBLIC_EVM_ATTESTATION",
            "reason": self.unavailable_reason,
            "network_label": self.network_label or None,
            "chain_id": self.chain_id,
            "live_chain_id": (
                last_preflight.get("chain_id") if last_preflight is not None else None
            ),
            "contract_address": self.contract_address or None,
            "schema_uid": self.schema_uid or None,
            "schema_definition": self.schema_definition,
            "checkpoint_schema_uid": self.checkpoint_schema_uid or None,
            "checkpoint_configured": bool(self.checkpoint_schema_uid),
            "checkpoint_schema_definition": (
                self.checkpoint_schema_definition if self.checkpoint_schema_uid else None
            ),
            "coattestation_schema_uid": self.coattestation_schema_uid or None,
            "coattestation_configured": bool(self.coattestation_schema_uid),
            "coattestation_schema_definition": (
                self.coattestation_schema_definition if self.coattestation_schema_uid else None
            ),
            "member_registry_address": self.member_registry_address or None,
            # Stated rather than implied: the attester key is an in-process
            # environment secret, not an HSM or KMS-held key.
            "attester_key_custody": "IN_PROCESS_ENVIRONMENT_SECRET",
            "finality_policy": self.finality_policy,
            "attester_address": self.required_attester_address or self.attester_address,
            "rpc_endpoint_count": len(self.rpc_urls),
        }


class ChainRequiredProofAnchor:
    """Explicit failure state when a chain anchor is required but not configured.

    Failing loudly is safer than silently downgrading to a local receipt and
    then describing it as blockchain during a demo.
    """

    name = "chain-anchor-required-unavailable"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.available = False

    def anchor(self, packet_hash: str) -> ProofReceipt:
        del packet_hash
        return ProofReceipt(
            status=AnchorStatus.FAILED,
            provider=self.name,
            receipt={
                "error_code": self.reason,
                "anchor_scope": "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
                "impact_note": (
                    "A public-chain anchor was required and is unavailable. The evidence "
                    "result is unaffected and remains locally verifiable."
                ),
            },
        )

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": False,
            "scope": "PUBLIC_EVM_ATTESTATION_REQUIRED",
            "reason": self.reason,
        }


class DurableTransparencyAnchor:
    """Database-backed transparency receipts.

    Equivalent guarantees to :class:`MerkleTransparencyAnchor` but the log lives
    in PostgreSQL/SQLite instead of a process-local file, so two workers or a
    container rebuild cannot fork it. It is still not a blockchain.
    """

    name = "durable-merkle-transparency-log-v2"

    def __init__(self, transparency_log, session_factory) -> None:
        self._log = transparency_log
        self._session_factory = session_factory
        self.available = True

    def anchor(self, packet_hash: str) -> ProofReceipt:
        if len(packet_hash) != 64:
            return ProofReceipt(
                status=AnchorStatus.FAILED,
                provider=self.name,
                receipt={"error_code": "INVALID_PACKET_HASH"},
            )
        db = self._session_factory()
        try:
            receipt = self._log.append(db, packet_hash=packet_hash)
        except Exception as exc:
            db.rollback()
            return ProofReceipt(
                status=AnchorStatus.FAILED,
                provider=self.name,
                receipt={"error_code": f"TRANSPARENCY_APPEND_FAILED:{type(exc).__name__}"},
            )
        finally:
            db.close()
        return ProofReceipt(
            status=(
                AnchorStatus.ANCHORED if receipt["inclusion_verified"] else AnchorStatus.FAILED
            ),
            provider=self.name,
            receipt=receipt,
        )

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": True,
            "scope": "LOCAL_TRANSPARENCY_LOG",
            "reason": "NOT_A_BLOCKCHAIN",
        }


def build_eas_anchor(settings) -> EASProofAnchor:
    configured_rpc_urls: list[str] = []
    rpc_urls_json = getattr(settings, "eas_rpc_urls_json", "")
    if rpc_urls_json:
        try:
            parsed_rpc_urls = json.loads(rpc_urls_json)
            if isinstance(parsed_rpc_urls, list):
                configured_rpc_urls = [str(value) for value in parsed_rpc_urls]
        except (json.JSONDecodeError, TypeError, ValueError):
            # Provider preflight will continue with the legacy primary RPC URL.
            configured_rpc_urls = []
    return EASProofAnchor(
        rpc_url=settings.eas_rpc_url,
        contract_address=settings.eas_contract_address,
        schema_uid=settings.eas_schema_uid,
        private_key=settings.eas_private_key,
        recipient=settings.eas_recipient,
        explorer_tx_base_url=settings.eas_explorer_tx_base_url,
        chain_id=settings.eas_chain_id,
        timeout_seconds=settings.eas_receipt_timeout_seconds,
        network_label=settings.eas_network_label,
        explorer_address_base_url=settings.eas_explorer_address_base_url,
        explorer_attestation_base_url=settings.eas_explorer_attestation_base_url,
        required_confirmations=settings.eas_required_confirmations,
        max_attempts=settings.eas_max_attempts,
        retry_backoff_seconds=settings.eas_retry_backoff_seconds,
        max_fee_per_gas_gwei=settings.eas_max_fee_per_gas_gwei,
        schema_registry_address=getattr(settings, "eas_schema_registry_address", ""),
        schema_definition=getattr(settings, "eas_schema_definition", "bytes32 packetHash"),
        expected_contract_code_sha256=getattr(settings, "eas_expected_contract_code_sha256", ""),
        rpc_urls=configured_rpc_urls,
        required_attester_address=getattr(settings, "eas_required_attester_address", ""),
        checkpoint_schema_uid=getattr(settings, "eas_checkpoint_schema_uid", ""),
        checkpoint_schema_definition=getattr(
            settings, "eas_checkpoint_schema_definition", "bytes32 checkpointHash"
        ),
        coattestation_schema_uid=(
            getattr(settings, "eas_coattestation_schema_uid", "")
            if getattr(settings, "blockchain_counterparty_attestation_enabled", False)
            else ""
        ),
        coattestation_schema_definition=getattr(
            settings, "eas_coattestation_schema_definition", "bytes32 coAttestationHash"
        ),
        member_registry_address=getattr(settings, "eas_member_registry_address", ""),
        finality_policy=getattr(settings, "eas_finality_policy", "confirmation_depth"),
    )


def build_proof_anchor(settings, *, transparency_log=None, session_factory=None):
    if settings.proof_anchor_mode == "none":
        return NoopProofAnchor()
    if settings.proof_anchor_mode in {"auto", "eas"}:
        eas = build_eas_anchor(settings)
        if eas.available or settings.proof_anchor_mode == "eas":
            return eas
        if settings.proof_require_chain:
            return ChainRequiredProofAnchor(eas.unavailable_reason or "EAS_UNAVAILABLE")
    if settings.proof_require_chain:
        return ChainRequiredProofAnchor("CHAIN_ANCHOR_REQUIRED_BUT_MODE_IS_LOCAL")
    if transparency_log is not None and session_factory is not None:
        return DurableTransparencyAnchor(transparency_log, session_factory)
    return MerkleTransparencyAnchor(settings.proof_log_path)
