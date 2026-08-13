#!/usr/bin/env python3
"""Register CreatorProof EAS schemas on Base Sepolia and print non-secret pins.

Usage (from apps/api, with funded CREATORPROOF_EAS_PRIVATE_KEY in .env):

    uv run --no-sync python -m scripts.provision_eas_base_sepolia

Never prints private keys. Writes suggested .env lines to stdout for the operator
to copy after independent verification on https://base-sepolia.easscan.org.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.services.blockchain import deployment_manifest  # noqa: E402
from app.services.crypto_ed25519 import public_key_from_seed  # noqa: E402

# Official Base Sepolia EAS deployments (public constants).
RPC_URL = "https://sepolia.base.org"
CHAIN_ID = 84532
EAS = "0x4200000000000000000000000000000000000021"
REGISTRY = "0x4200000000000000000000000000000000000020"
ZERO = "0x0000000000000000000000000000000000000000"

REGISTRY_ABI = [
    {
        "inputs": [
            {"internalType": "string", "name": "schema", "type": "string"},
            {"internalType": "address", "name": "resolver", "type": "address"},
            {"internalType": "bool", "name": "revocable", "type": "bool"},
        ],
        "name": "register",
        "outputs": [{"internalType": "bytes32", "name": "", "type": "bytes32"}],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "bytes32", "name": "uid", "type": "bytes32"},
            {"indexed": True, "internalType": "address", "name": "registerer", "type": "address"},
        ],
        "name": "Registered",
        "type": "event",
    },
    {
        "inputs": [{"internalType": "bytes32", "name": "uid", "type": "bytes32"}],
        "name": "getSchema",
        "outputs": [
            {
                "components": [
                    {"internalType": "bytes32", "name": "uid", "type": "bytes32"},
                    {"internalType": "address", "name": "resolver", "type": "address"},
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
    },
]


def _load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        if not line or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _uid_hex(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return "0x" + value.hex()
    return value if value.startswith("0x") else "0x" + value


def _register(w3: Web3, account, schema: str, *, revocable: bool) -> str:
    registry = w3.eth.contract(address=Web3.to_checksum_address(REGISTRY), abi=REGISTRY_ABI)
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    tx = registry.functions.register(schema, ZERO, revocable).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "chainId": CHAIN_ID,
            "gas": 400_000,
            "maxFeePerGas": w3.eth.gas_price * 2,
            "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei"),
        }
    )
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"submitted {schema!r} revocable={revocable} tx={tx_hash.hex()}")
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
    if receipt.status != 1:
        raise RuntimeError(f"schema registration failed: {tx_hash.hex()}")
    logs = registry.events.Registered().process_receipt(receipt)
    if not logs:
        raise RuntimeError("Registered event missing from receipt")
    uid = _uid_hex(logs[0]["args"]["uid"])
    record = registry.functions.getSchema(uid).call()
    print(
        json.dumps(
            {
                "schema": record[3],
                "resolver": record[1],
                "revocable": record[2],
                "uid": uid,
                "tx": tx_hash.hex(),
                "explorer_tx": f"https://sepolia-explorer.base.org/tx/{tx_hash.hex()}",
                "easscan": f"https://base-sepolia.easscan.org/schema/view/{uid}",
            },
            indent=2,
        )
    )
    return uid


def main() -> int:
    env_path = ROOT / ".env"
    env = _load_env(env_path)
    pk = env.get("CREATORPROOF_EAS_PRIVATE_KEY", "")
    if not pk:
        print("CREATORPROOF_EAS_PRIVATE_KEY is missing from apps/api/.env", file=sys.stderr)
        return 2
    if not pk.startswith("0x"):
        pk = "0x" + pk
    account = Account.from_key(pk)
    w3 = Web3(Web3.HTTPProvider(RPC_URL, request_kwargs={"timeout": 30}))
    if int(w3.eth.chain_id) != CHAIN_ID:
        print(f"unexpected chain id {w3.eth.chain_id}", file=sys.stderr)
        return 2
    balance = w3.eth.get_balance(account.address)
    code = bytes(w3.eth.get_code(Web3.to_checksum_address(EAS)))
    code_sha = hashlib.sha256(code).hexdigest()
    print(
        json.dumps(
            {
                "attester": account.address,
                "balance_wei": balance,
                "balance_eth": float(w3.from_wei(balance, "ether")),
                "eas_code_sha256": code_sha,
                "rpc": RPC_URL,
                "chain_id": CHAIN_ID,
            },
            indent=2,
        )
    )
    if balance == 0:
        print(
            "\nFund this attester with Base Sepolia ETH, then re-run:\n"
            f"  address: {account.address}\n"
            "  faucets: https://docs.base.org/base-chain/network-information/network-faucets\n",
            file=sys.stderr,
        )
        return 3

    packet_uid = env.get("CREATORPROOF_EAS_SCHEMA_UID", "").strip()
    checkpoint_uid = env.get("CREATORPROOF_EAS_CHECKPOINT_SCHEMA_UID", "").strip()
    registry = w3.eth.contract(address=Web3.to_checksum_address(REGISTRY), abi=REGISTRY_ABI)

    def schema_ok(uid: str, expected: str, revocable: bool) -> bool:
        if not uid:
            return False
        try:
            record = registry.functions.getSchema(uid).call()
        except Exception:
            return False
        return record[3] == expected and bool(record[2]) is revocable and record[1] == ZERO

    if not schema_ok(packet_uid, "bytes32 packetHash", True):
        packet_uid = _register(w3, account, "bytes32 packetHash", revocable=True)
        time.sleep(2)
    else:
        print(f"reusing packet schema {packet_uid}")

    if not schema_ok(checkpoint_uid, "bytes32 checkpointHash", False):
        checkpoint_uid = _register(w3, account, "bytes32 checkpointHash", revocable=False)
    else:
        print(f"reusing checkpoint schema {checkpoint_uid}")

    stmt = env.get("CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX", "")
    issuer_fp = None
    if stmt:
        seed = bytes.fromhex(stmt.removeprefix("0x"))
        issuer_fp = hashlib.sha256(public_key_from_seed(seed)).hexdigest()

    # Build a settings-like object for deployment fingerprint.
    settings = Settings(
        _env_file=None,
        proof_anchor_mode="eas",
        proof_require_chain=True,
        eas_rpc_url=RPC_URL,
        eas_chain_id=CHAIN_ID,
        eas_contract_address=EAS,
        eas_schema_uid=packet_uid,
        eas_checkpoint_schema_uid=checkpoint_uid,
        eas_schema_definition="bytes32 packetHash",
        eas_checkpoint_schema_definition="bytes32 checkpointHash",
        eas_recipient=ZERO,
        eas_required_attester_address=account.address,
        eas_expected_contract_code_sha256=code_sha,
        eas_finality_policy="safe",
        eas_private_key=pk,
        statement_signing_private_key_hex=stmt,
        trusted_issuer_key_sha256=issuer_fp or "",
        blockchain_domain_anchoring_enabled=True,
    )
    manifest = deployment_manifest(settings)
    deployment_fp = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    print("\n# --- copy into apps/api/.env after verifying schemas on easscan ---")
    print("CREATORPROOF_PROOF_ANCHOR_MODE=eas")
    print("CREATORPROOF_PROOF_REQUIRE_CHAIN=true")
    print(f"CREATORPROOF_EAS_RPC_URL={RPC_URL}")
    print('CREATORPROOF_EAS_RPC_URLS_JSON=["https://sepolia.base.org"]')
    print(f"CREATORPROOF_EAS_CHAIN_ID={CHAIN_ID}")
    print("CREATORPROOF_EAS_NETWORK_LABEL=Base Sepolia")
    print(f"CREATORPROOF_EAS_CONTRACT_ADDRESS={EAS}")
    print(f"CREATORPROOF_EAS_SCHEMA_REGISTRY_ADDRESS={REGISTRY}")
    print("CREATORPROOF_EAS_SCHEMA_DEFINITION=bytes32 packetHash")
    print(f"CREATORPROOF_EAS_SCHEMA_UID={packet_uid}")
    print("CREATORPROOF_EAS_CHECKPOINT_SCHEMA_DEFINITION=bytes32 checkpointHash")
    print(f"CREATORPROOF_EAS_CHECKPOINT_SCHEMA_UID={checkpoint_uid}")
    print(f"CREATORPROOF_EAS_EXPECTED_CONTRACT_CODE_SHA256={code_sha}")
    print(f"CREATORPROOF_EAS_REQUIRED_ATTESTER_ADDRESS={account.address}")
    print(f"CREATORPROOF_EAS_RECIPIENT={ZERO}")
    print("CREATORPROOF_EAS_EXPLORER_TX_BASE_URL=https://sepolia-explorer.base.org/tx")
    print("CREATORPROOF_EAS_EXPLORER_ADDRESS_BASE_URL=https://sepolia-explorer.base.org/address")
    print(
        "CREATORPROOF_EAS_EXPLORER_ATTESTATION_BASE_URL=https://base-sepolia.easscan.org/attestation/view"
    )
    print("CREATORPROOF_EAS_REQUIRED_CONFIRMATIONS=2")
    print("CREATORPROOF_EAS_FINALITY_POLICY=safe")
    print("CREATORPROOF_BLOCKCHAIN_DOMAIN_ANCHORING_ENABLED=true")
    if issuer_fp:
        print(f"CREATORPROOF_TRUSTED_ISSUER_KEY_SHA256={issuer_fp}")
        print(f"NEXT_PUBLIC_CREATORPROOF_ISSUER_KEY_FINGERPRINT_SHA256={issuer_fp}")
    print(f"NEXT_PUBLIC_CREATORPROOF_DEPLOYMENT_FINGERPRINT_SHA256={deployment_fp}")
    print("NEXT_PUBLIC_CREATORPROOF_ISSUER=creatorproof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
