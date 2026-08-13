from __future__ import annotations

import json

import pytest

from scripts.verify_proof_receipt import (
    _deployment_fingerprint,
    _load_deployment_manifest,
    _verify_chain,
)


def _manifest() -> dict:
    return {
        "schema": "creatorproof.blockchain_deployment.v1",
        "chain_id": 84532,
        "contract_address": "0x" + "11" * 20,
        "schema_uid": "0x" + "22" * 32,
        "checkpoint_schema_uid": "0x" + "33" * 32,
        "schema_definition": "bytes32 packetHash",
        "checkpoint_schema_definition": "bytes32 checkpointHash",
        "recipient": "0x" + "44" * 20,
        "required_attester_address": "0x" + "55" * 20,
        "expected_contract_code_sha256": "66" * 32,
        "finality_policy": "safe",
    }


def test_deployment_manifest_fingerprint_is_canonical_and_exact(tmp_path):
    manifest = _manifest()
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps({"manifest": manifest}, indent=2), encoding="utf-8")

    loaded = _load_deployment_manifest(path)

    assert loaded == manifest
    assert _deployment_fingerprint(loaded) == _deployment_fingerprint(
        dict(reversed(list(manifest.items())))
    )


def test_deployment_manifest_requires_contract_bytecode_pin(tmp_path):
    manifest = _manifest()
    manifest["expected_contract_code_sha256"] = ""
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="PINNED_CONTRACT_CODE_HASH"):
        _load_deployment_manifest(path)


def test_receipt_fields_cannot_supply_live_chain_trust_roots():
    receipt = {
        "attestation_uid": "0x" + "77" * 32,
        "contract_address": "0x" + "88" * 20,
        "schema_uid": "0x" + "99" * 32,
        "attester_address": "0x" + "aa" * 20,
        "recipient": "0x" + "bb" * 20,
        "chain_id": 84532,
        "packet_hash_sha256": "cc" * 32,
    }

    result = _verify_chain(
        receipt,
        "https://rpc.example.invalid",
        manifest=None,
        expected_deployment_fingerprint=None,
        expected_commitment_hash=None,
    )

    assert result["valid"] is False
    assert result["error"] == "INDEPENDENT_TRUST_ROOTS_REQUIRED"
