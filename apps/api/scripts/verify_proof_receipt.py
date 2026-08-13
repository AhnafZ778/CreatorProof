"""Verify a CreatorProof proof receipt.

Two receipt kinds are supported and are never conflated:

* ``creatorproof.eas_receipt.*`` — a public EVM attestation of the canonical
  packet hash. With ``--rpc-url`` the attestation UID is re-checked against the
  live EAS contract, which is what an independent verifier should do.
* ``creatorproof.transparency_receipt.*`` and the older local Merkle receipt — an
  append-only transparency receipt. This is cryptographic audit infrastructure,
  not a blockchain, and the output says so explicitly.

``--help`` works without the optional blockchain runtime installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from app.providers.proof import verify_merkle_receipt

LOCAL_SCHEMAS = {
    "creatorproof.transparency_leaf.v1",
    "creatorproof.transparency_receipt.v2",
}


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Accept a full scan body, an evidence packet, or a bare receipt.
    for key in ("evidence_packet", "proof"):
        if isinstance(payload, dict) and key in payload and isinstance(payload[key], dict):
            payload = payload[key]
    if isinstance(payload, dict) and isinstance(payload.get("receipt"), dict):
        return payload["receipt"]
    return payload


def _load_deployment_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(manifest, dict) and isinstance(manifest.get("manifest"), dict):
        manifest = manifest["manifest"]
    required = {
        "schema",
        "chain_id",
        "contract_address",
        "schema_uid",
        "checkpoint_schema_uid",
        "schema_definition",
        "checkpoint_schema_definition",
        "recipient",
        "required_attester_address",
        "expected_contract_code_sha256",
        "finality_policy",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        missing = sorted(required - set(manifest if isinstance(manifest, dict) else {}))
        extra = sorted(set(manifest if isinstance(manifest, dict) else {}) - required)
        raise ValueError(f"INVALID_DEPLOYMENT_MANIFEST missing={missing} extra={extra}")
    if manifest.get("schema") != "creatorproof.blockchain_deployment.v1":
        raise ValueError("INVALID_DEPLOYMENT_MANIFEST_SCHEMA")
    code_hash = str(manifest.get("expected_contract_code_sha256") or "").removeprefix("0x")
    if len(code_hash) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in code_hash
    ):
        raise ValueError("DEPLOYMENT_MANIFEST_REQUIRES_PINNED_CONTRACT_CODE_HASH")
    return manifest


def _deployment_fingerprint(manifest: dict) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_local(receipt: dict) -> dict:
    valid = verify_merkle_receipt(
        str(receipt.get("packet_hash_sha256", "")),
        str(receipt.get("root_sha256", "")),
        list(receipt.get("inclusion_proof") or []),
    )
    return {
        "receipt_kind": "LOCAL_TRANSPARENCY_RECEIPT",
        "valid": valid,
        "log_id": receipt.get("log_id"),
        "leaf_index": receipt.get("leaf_index") or receipt.get("index"),
        "tree_size": receipt.get("tree_size"),
        "root_sha256": receipt.get("root_sha256"),
        "scope": receipt.get("anchor_scope"),
        "is_blockchain": False,
        "warning": (
            "A local Merkle receipt is an append-only transparency record. It is not a "
            "public blockchain transaction and must never be presented as one."
        ),
    }


def _verify_chain(
    receipt: dict,
    rpc_url: str | None,
    *,
    manifest: dict | None,
    expected_deployment_fingerprint: str | None,
    expected_commitment_hash: str | None,
) -> dict:
    result = {
        "receipt_kind": "PUBLIC_EVM_ATTESTATION",
        "is_blockchain": True,
        "chain_id": receipt.get("chain_id"),
        "network_label": receipt.get("network_label"),
        "contract_address": receipt.get("contract_address"),
        "schema_uid": receipt.get("schema_uid"),
        "attester_address": receipt.get("attester_address"),
        "transaction_hash": receipt.get("transaction_hash"),
        "block_number": receipt.get("block_number"),
        "attestation_uid": receipt.get("attestation_uid"),
        "packet_hash_sha256": receipt.get("packet_hash_sha256"),
        "explorer": receipt.get("explorer"),
        "recorded_attestation_valid": receipt.get("attestation_valid"),
        "committed_value": "bytes32 packetHash",
        "note": (
            "The attestation commits the packet identity and its time. It does not "
            "establish that the underlying evidence or any rights claim is true."
        ),
    }
    if not rpc_url:
        result["valid"] = False
        result["verification_source"] = "UNVERIFIED_RECORDED_RECEIPT"
        result["hint"] = (
            "A receipt cannot authenticate itself. Pass --rpc-url plus the separately "
            "pinned deployment fields to re-check the full attestation."
        )
        return result

    if manifest is None or not expected_deployment_fingerprint or not expected_commitment_hash:
        result["valid"] = False
        result["verification_source"] = "LIVE_CHAIN_NOT_ATTEMPTED"
        result["error"] = "INDEPENDENT_TRUST_ROOTS_REQUIRED"
        result["hint"] = (
            "Live verification requires --deployment-manifest, "
            "--expect-deployment-fingerprint and --expect-packet-hash."
        )
        return result

    normalized_fingerprint = expected_deployment_fingerprint.lower().removeprefix("sha256:")
    computed_fingerprint = _deployment_fingerprint(manifest)
    if (
        len(normalized_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in normalized_fingerprint)
        or computed_fingerprint != normalized_fingerprint
    ):
        result["valid"] = False
        result["verification_source"] = "DEPLOYMENT_MANIFEST"
        result["error"] = "DEPLOYMENT_FINGERPRINT_MISMATCH"
        result["computed_deployment_fingerprint_sha256"] = computed_fingerprint
        return result

    uid = str(receipt.get("attestation_uid") or "")
    if not uid:
        result["valid"] = False
        result["verification_source"] = "LIVE_CHAIN"
        result["error"] = "RECEIPT_HAS_NO_ATTESTATION_UID"
        return result
    try:
        from app.providers.proof import EASProofAnchor
    except Exception as exc:  # pragma: no cover - import guard
        result["valid"] = False
        result["error"] = f"RUNTIME_UNAVAILABLE:{type(exc).__name__}"
        return result

    anchor = EASProofAnchor(
        rpc_url=rpc_url,
        contract_address=str(manifest["contract_address"]),
        schema_uid=str(manifest["schema_uid"]),
        # A read-only check still needs a key-shaped value to construct the client;
        # it is never used to sign, and no transaction is submitted here.
        private_key="0x" + "11" * 32,
        recipient=str(manifest["recipient"]),
        explorer_tx_base_url="",
        chain_id=int(manifest["chain_id"]),
        timeout_seconds=30,
        # The placeholder key is never used for signing. The independently
        # pinned attester is enforced below as verification metadata.
        required_attester_address="",
        checkpoint_schema_uid=str(manifest["checkpoint_schema_uid"]),
        schema_definition=str(manifest["schema_definition"]),
        checkpoint_schema_definition=str(manifest["checkpoint_schema_definition"]),
        expected_contract_code_sha256=str(manifest["expected_contract_code_sha256"]),
        finality_policy=str(manifest["finality_policy"]),
    )
    commitment_type = str(receipt.get("commitment_type") or "EVIDENCE_PACKET")
    schema_uid = (
        manifest["checkpoint_schema_uid"]
        if commitment_type == "TRANSPARENCY_CHECKPOINT"
        else manifest["schema_uid"]
    )
    live = anchor.verify(
        attestation_uid=uid,
        expected_commitment_hash=expected_commitment_hash,
        expected_metadata={
            "commitment_type": commitment_type,
            "chain_id": manifest["chain_id"],
            "contract_address": manifest["contract_address"],
            "schema_uid": schema_uid,
            "attester_address": manifest["required_attester_address"],
            "recipient": manifest["recipient"],
        },
    )
    result["verification_source"] = "LIVE_CHAIN"
    result["live_check"] = live
    result["valid"] = bool(live.get("attestation_valid") and live.get("binding_matches") is True)
    result["deployment_fingerprint_sha256"] = computed_fingerprint
    result["expected_commitment_hash_sha256"] = expected_commitment_hash
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a CreatorProof proof receipt (EAS attestation or local receipt)."
    )
    parser.add_argument("receipt", type=Path, help="Receipt, evidence packet or scan JSON file.")
    parser.add_argument(
        "--rpc-url",
        default=None,
        help="EVM RPC endpoint used to re-check an attestation UID on chain.",
    )
    parser.add_argument(
        "--expect-packet-hash",
        default=None,
        help=(
            "Independently obtained canonical packet/checkpoint SHA-256 commitment. "
            "Required for live-chain reliance."
        ),
    )
    parser.add_argument(
        "--deployment-manifest",
        type=Path,
        default=None,
        help="Independently obtained CreatorProof blockchain deployment manifest JSON.",
    )
    parser.add_argument(
        "--expect-deployment-fingerprint",
        default=None,
        help="Independently pinned SHA-256 fingerprint of the deployment manifest.",
    )
    args = parser.parse_args()

    receipt = _load(args.receipt)
    schema = str(receipt.get("schema", ""))
    manifest = None
    if args.deployment_manifest is not None:
        try:
            manifest = _load_deployment_manifest(args.deployment_manifest)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
            return 2
    if schema.startswith("creatorproof.eas_receipt") or receipt.get("attestation_uid"):
        result = _verify_chain(
            receipt,
            args.rpc_url,
            manifest=manifest,
            expected_deployment_fingerprint=args.expect_deployment_fingerprint,
            expected_commitment_hash=args.expect_packet_hash,
        )
    elif schema in LOCAL_SCHEMAS or "inclusion_proof" in receipt:
        result = _verify_local(receipt)
    else:
        print(
            json.dumps(
                {"valid": False, "error": "UNRECOGNIZED_RECEIPT_SCHEMA", "schema": schema},
                indent=2,
            )
        )
        return 2

    if args.expect_packet_hash:
        recorded = (
            receipt.get("commitment_hash_sha256")
            or receipt.get("packet_hash_sha256")
            or receipt.get("checkpoint_hash_sha256")
        )
        if recorded:
            matches = str(recorded).lower().removeprefix("0x") == str(
                args.expect_packet_hash
            ).lower().removeprefix("0x")
            result["recorded_receipt_matches_expected"] = matches
            result["valid"] = bool(result.get("valid")) and matches

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid") else 1


if __name__ == "__main__":
    sys.exit(main())
