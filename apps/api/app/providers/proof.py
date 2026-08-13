from __future__ import annotations

import hashlib
import json
import math
import threading
from datetime import UTC, datetime
from pathlib import Path

from app.domain.enums import AnchorStatus
from app.providers.contracts import ProofReceipt


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
]


class EASProofAnchor:
    """Submit a packet commitment to Ethereum Attestation Service.

    The configured EAS schema must be exactly ``bytes32 packetHash``. No media,
    claimant identity, detector output, or private evidence is placed on chain.
    """

    name = "ethereum-attestation-service-onchain-v1"

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
    ) -> None:
        self.rpc_url = rpc_url
        self.contract_address = contract_address
        self.schema_uid = schema_uid
        self.private_key = private_key
        self.recipient = recipient
        self.explorer_tx_base_url = explorer_tx_base_url.rstrip("/")
        self.chain_id = chain_id
        self.timeout_seconds = timeout_seconds
        self.available = False
        self.unavailable_reason: str | None = None
        self._web3 = None
        if not all((rpc_url, contract_address, schema_uid, private_key)):
            self.unavailable_reason = "EAS_CONFIGURATION_INCOMPLETE"
            return
        try:
            from web3 import Web3  # type: ignore

            self._web3 = Web3
            if not Web3.is_address(contract_address):
                raise ValueError("invalid EAS contract or schema")
            _bytes32(schema_uid)
            self.available = True
        except (ImportError, ValueError) as exc:
            self.unavailable_reason = f"EAS_RUNTIME_UNAVAILABLE:{type(exc).__name__}"

    def anchor(self, packet_hash: str) -> ProofReceipt:
        if not self.available or self._web3 is None:
            return ProofReceipt(
                status=AnchorStatus.FAILED,
                provider=self.name,
                receipt={"error_code": self.unavailable_reason or "EAS_UNAVAILABLE"},
            )
        try:
            from eth_abi import encode  # type: ignore

            web3 = self._web3(self._web3.HTTPProvider(self.rpc_url))
            account = web3.eth.account.from_key(self.private_key)
            contract = web3.eth.contract(
                address=self._web3.to_checksum_address(self.contract_address), abi=_EAS_ABI
            )
            encoded = encode(["bytes32"], [bytes.fromhex(packet_hash)])
            request = (
                _bytes32(self.schema_uid),
                (
                    self._web3.to_checksum_address(self.recipient),
                    0,
                    False,
                    bytes(32),
                    encoded,
                    0,
                ),
            )
            chain_id = self.chain_id or int(web3.eth.chain_id)
            transaction = contract.functions.attest(request).build_transaction(
                {
                    "from": account.address,
                    "nonce": web3.eth.get_transaction_count(account.address, "pending"),
                    "chainId": chain_id,
                    "gasPrice": web3.eth.gas_price,
                    "value": 0,
                }
            )
            estimate = web3.eth.estimate_gas(transaction)
            transaction["gas"] = max(100_000, math.ceil(estimate * 1.2))
            signed = account.sign_transaction(transaction)
            tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
            mined = web3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=self.timeout_seconds, poll_latency=1
            )
            events = contract.events.Attested().process_receipt(mined)
            uid = events[0]["args"]["uid"].hex() if events else None
            valid = bool(uid and contract.functions.isAttestationValid(_bytes32(uid)).call())
            tx_hex = tx_hash.hex()
            receipt = {
                "schema": "creatorproof.eas_receipt.v1",
                "packet_hash_sha256": packet_hash,
                "chain_id": chain_id,
                "contract_address": self.contract_address,
                "schema_uid": self.schema_uid,
                "transaction_hash": tx_hex,
                "block_number": int(mined.blockNumber),
                "attestation_uid": f"0x{uid}" if uid else None,
                "attestation_valid": valid,
                "explorer_url": (
                    f"{self.explorer_tx_base_url}/{tx_hex}" if self.explorer_tx_base_url else None
                ),
                "anchor_scope": "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
            }
            anchor_status = (
                AnchorStatus.ANCHORED if int(mined.status) == 1 and valid else AnchorStatus.FAILED
            )
            return ProofReceipt(
                status=anchor_status,
                provider=self.name,
                receipt=receipt,
            )
        except Exception as exc:
            return ProofReceipt(
                status=AnchorStatus.FAILED,
                provider=self.name,
                receipt={"error_code": f"EAS_ANCHOR_FAILED:{type(exc).__name__}"},
            )

    def status(self) -> dict:
        return {
            "provider": self.name,
            "available": self.available,
            "scope": "PUBLIC_EVM_ATTESTATION",
            "reason": self.unavailable_reason,
        }


def build_proof_anchor(settings):
    if settings.proof_anchor_mode == "none":
        return NoopProofAnchor()
    if settings.proof_anchor_mode in {"auto", "eas"}:
        eas = EASProofAnchor(
            rpc_url=settings.eas_rpc_url,
            contract_address=settings.eas_contract_address,
            schema_uid=settings.eas_schema_uid,
            private_key=settings.eas_private_key,
            recipient=settings.eas_recipient,
            explorer_tx_base_url=settings.eas_explorer_tx_base_url,
            chain_id=settings.eas_chain_id,
            timeout_seconds=settings.eas_receipt_timeout_seconds,
        )
        if eas.available or settings.proof_anchor_mode == "eas":
            return eas
    return MerkleTransparencyAnchor(settings.proof_log_path)
