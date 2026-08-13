"""Adversarial tests for the fail-closed offline evidence verifier."""

from __future__ import annotations

import base64
import copy
import hashlib
import json

import pytest

from app.services.signing import StatementSigner
from app.services.transparency import leaf_hash, node_hash
from scripts.verify_evidence_statement import verify_package


@pytest.fixture
def signed_package_factory():
    signer = StatementSigner(
        kid="issuer-2026",
        private_key_hex="11" * 32,
        fallback_material="unused",
    )

    def signature(payload: dict) -> dict:
        signed = signer.sign(payload)
        return {
            "alg": signed["signature_alg"],
            "kid": signed["signature_kid"],
            "signature_b64": signed["signature_b64"],
            "cose_sign1_b64": signed["cose_sign1_b64"],
            "payload_digest_sha256": signed["payload_digest_sha256"],
        }

    root = {
        "schema": "creatorproof.statement.v2",
        "statement_id": "stm_root",
        "statement_type": "RESULT",
        "issuer": "creatorproof",
        "tenant_id": "tenant_a",
        "scan_id": "scan_a",
        "created_at": "2026-08-12T00:00:00+00:00",
        "previous_statement_id": None,
        "decision": {"policy_action": "REVIEW"},
    }
    root_signature = signature(root)
    root_digest = root_signature["payload_digest_sha256"]
    root_leaf = leaf_hash(root_digest)
    checkpoint_body = {
        "log_id": "creatorproof-statements",
        "tree_size": 1,
        "root_sha256": root_leaf.hex(),
    }
    checkpoint_signature = signature(checkpoint_body)

    packet = {"scan_id": "scan_a", "decision": {"policy_action": "REVIEW"}}
    packet_bytes = json.dumps(
        packet,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    proof_binding = {
        "packet_hash_sha256": hashlib.sha256(packet_bytes).hexdigest(),
        "proof_kind": "EVIDENCE_PACKET",
    }
    proof_binding_signature = signature(proof_binding)

    lineage = [
        {
            "statement": root,
            "payload_digest_sha256": root_digest,
            "statement_type": "RESULT",
            "previous_statement_id": None,
            "status": "ACTIVE",
            "signature": root_signature,
        }
    ]
    lineage_binding = {
        "schema": "creatorproof.statement_lineage_binding.v1",
        "scan_id": "scan_a",
        "root_statement_id": "stm_root",
        "current_status": "ACTIVE",
        "statement_ids": ["stm_root"],
        "payload_digests_sha256": [root_digest],
        "checkpoint": checkpoint_body,
    }
    lineage_binding_signature = signature(lineage_binding)
    fingerprint = hashlib.sha256(bytes.fromhex(signer.public_key_hex)).hexdigest()

    package = {
        "schema": "creatorproof.verification_package.v1",
        "statement": root,
        "signature": root_signature,
        "payload_digest_sha256": root_digest,
        "status": "ACTIVE",
        "statement_lineage": lineage,
        "statement_lineage_binding": lineage_binding,
        "statement_lineage_binding_signature": lineage_binding_signature,
        "evidence_packet_without_proof": packet,
        "evidence_packet_canonical_b64": base64.b64encode(packet_bytes).decode("ascii"),
        "proof_binding": proof_binding,
        "proof_binding_signature": proof_binding_signature,
        "deployment": {"issuer_key_fingerprint_sha256": fingerprint},
        "trust_bundle": {
            "keys": [
                {
                    "kid": signer.kid,
                    "algorithm": "Ed25519",
                    "public_key_hex": signer.public_key_hex,
                    "active": True,
                }
            ]
        },
        "transparency": {
            "log_id": checkpoint_body["log_id"],
            "leaf_index": 0,
            "leaf_hash_sha256": root_leaf.hex(),
            "packet_hash_sha256": root_digest,
            "tree_size": 1,
            "root_sha256": root_leaf.hex(),
            "inclusion_proof": [],
            "latest_checkpoint": {
                "tree_size": 1,
                "root_sha256": root_leaf.hex(),
                "signature_kid": checkpoint_signature["kid"],
                "signature_b64": checkpoint_signature["signature_b64"],
            },
        },
    }

    def factory() -> tuple[dict, str, StatementSigner]:
        return copy.deepcopy(package), fingerprint, signer

    return factory


def _checks(result: dict) -> dict[str, dict]:
    return {check["name"]: check for check in result["checks"]}


def _append_status_event(package: dict, signer: StatementSigner, event_type: str) -> None:
    previous = package["statement_lineage"][-1]
    previous_payload = previous["statement"]
    payload = {
        "schema": "creatorproof.statement.v2",
        "statement_id": f"stm_{event_type.lower()}",
        "statement_type": event_type,
        "issuer": "creatorproof",
        "tenant_id": previous_payload["tenant_id"],
        "scan_id": previous_payload["scan_id"],
        "created_at": "2026-08-12T00:01:00+00:00",
        "previous_statement_id": previous_payload["statement_id"],
        "previous_payload_digest_sha256": previous["payload_digest_sha256"],
        "reason": "auditor review",
    }
    signed = signer.sign(payload)
    signature = {
        "alg": signed["signature_alg"],
        "kid": signed["signature_kid"],
        "signature_b64": signed["signature_b64"],
        "cose_sign1_b64": signed["cose_sign1_b64"],
        "payload_digest_sha256": signed["payload_digest_sha256"],
    }
    package["statement_lineage"].append(
        {
            "statement": payload,
            "payload_digest_sha256": signed["payload_digest_sha256"],
            "statement_type": event_type,
            "previous_statement_id": payload["previous_statement_id"],
            "status": "ACTIVE",
            "signature": signature,
        }
    )
    derived_status = {
        "CORRECTION": "SUPERSEDED",
        "DISPUTE": "DISPUTED",
        "SUPERSESSION": "SUPERSEDED",
        "REVOCATION": "REVOKED",
    }[event_type]
    binding = package["statement_lineage_binding"]
    binding["current_status"] = derived_status
    binding["statement_ids"].append(payload["statement_id"])
    binding["payload_digests_sha256"].append(signed["payload_digest_sha256"])
    binding_signed = signer.sign(binding)
    package["statement_lineage_binding_signature"] = {
        "alg": binding_signed["signature_alg"],
        "kid": binding_signed["signature_kid"],
        "signature_b64": binding_signed["signature_b64"],
        "cose_sign1_b64": binding_signed["cose_sign1_b64"],
        "payload_digest_sha256": binding_signed["payload_digest_sha256"],
    }


def test_strong_package_verifies_all_required_signed_layers(signed_package_factory):
    package, fingerprint, _ = signed_package_factory()

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    assert result["valid"] is True, result["checks"]
    assert result["derived_status"] == "ACTIVE"
    checks = _checks(result)
    assert checks["checkpoint_signature"]["result"] == "PASS"
    assert checks["transparency"]["result"] == "PASS"
    assert checks["statement_lineage"]["result"] == "PASS"
    assert checks["lineage_binding"]["result"] == "PASS"


@pytest.mark.parametrize("fingerprint", [None, "", "00" * 32])
def test_external_issuer_fingerprint_is_mandatory_and_not_self_asserted(
    signed_package_factory, fingerprint
):
    package, _, _ = signed_package_factory()

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    assert result["valid"] is False
    assert _checks(result)["signature"]["result"] == "FAIL"


def test_unsigned_replacement_merkle_root_cannot_pass(signed_package_factory):
    package, fingerprint, _ = signed_package_factory()
    original_leaf = bytes.fromhex(package["transparency"]["leaf_hash_sha256"])
    sibling = hashlib.sha256(b"untrusted sibling").digest()
    substituted_root = node_hash(original_leaf, sibling).hex()

    # This is a perfectly self-consistent inclusion path, but no issuer signed
    # this two-leaf checkpoint.
    package["transparency"].update(
        {
            "tree_size": 2,
            "root_sha256": substituted_root,
            "inclusion_proof": [{"side": "right", "hash": sibling.hex()}],
        }
    )
    package["transparency"]["latest_checkpoint"].update(
        {"tree_size": 2, "root_sha256": substituted_root}
    )
    package["statement_lineage_binding"]["checkpoint"].update(
        {"tree_size": 2, "root_sha256": substituted_root}
    )

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    checks = _checks(result)
    assert checks["transparency"]["result"] == "PASS"
    assert checks["checkpoint_signature"]["result"] == "FAIL"
    assert result["valid"] is False


def test_inclusion_path_must_match_signed_index_and_tree_size(signed_package_factory):
    package, fingerprint, _ = signed_package_factory()
    package["transparency"]["inclusion_proof"] = [{"side": "right", "hash": "22" * 32}]

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    assert result["valid"] is False
    check = _checks(result)["transparency"]
    assert check["result"] == "FAIL"
    assert "PROOF_HAS_EXTRA_STEPS" in check["detail"]


def test_every_lineage_signature_is_verified(signed_package_factory):
    package, fingerprint, signer = signed_package_factory()
    _append_status_event(package, signer, "DISPUTE")
    package["statement_lineage"][1]["signature"]["signature_b64"] = base64.b64encode(
        b"\x00" * 64
    ).decode("ascii")

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    assert result["valid"] is False
    assert "INVALID_LINEAGE_SIGNATURE" in _checks(result)["statement_lineage"]["detail"]


def test_even_validly_signed_lineage_records_must_form_one_chain(signed_package_factory):
    package, fingerprint, signer = signed_package_factory()
    _append_status_event(package, signer, "DISPUTE")
    child = package["statement_lineage"][1]
    child["statement"]["previous_statement_id"] = "stm_foreign"
    child["previous_statement_id"] = "stm_foreign"
    resigned = signer.sign(child["statement"])
    child["payload_digest_sha256"] = resigned["payload_digest_sha256"]
    child["signature"] = {
        "alg": resigned["signature_alg"],
        "kid": resigned["signature_kid"],
        "signature_b64": resigned["signature_b64"],
        "cose_sign1_b64": resigned["cose_sign1_b64"],
        "payload_digest_sha256": resigned["payload_digest_sha256"],
    }

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    assert result["valid"] is False
    assert "BROKEN_LINEAGE_LINK" in _checks(result)["statement_lineage"]["detail"]


def test_lineage_binding_is_signed_and_exact(signed_package_factory):
    package, fingerprint, _ = signed_package_factory()
    package["statement_lineage_binding"]["statement_ids"].append("stm_injected")

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    assert result["valid"] is False
    binding = _checks(result)["lineage_binding"]
    assert binding["result"] == "FAIL"
    assert "fields_match=False" in binding["detail"]


def test_mutable_outer_status_is_ignored(signed_package_factory):
    package, fingerprint, _ = signed_package_factory()
    package["status"] = "REVOKED"
    package["statement_lineage"][0]["status"] = "REVOKED"

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    assert result["valid"] is True, result["checks"]
    assert result["derived_status"] == "ACTIVE"


def test_signed_status_lineage_determines_current_status(signed_package_factory):
    package, fingerprint, signer = signed_package_factory()
    _append_status_event(package, signer, "DISPUTE")
    package["status"] = "ACTIVE"

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    checks = _checks(result)
    assert checks["statement_lineage"]["result"] == "PASS"
    assert checks["lineage_binding"]["result"] == "PASS"
    assert checks["derived_statement_status"]["result"] == "ATTENTION"
    assert result["derived_status"] == "DISPUTED"
    assert result["valid"] is False


def test_multi_step_signed_status_lineage_uses_the_linear_tip(signed_package_factory):
    package, fingerprint, signer = signed_package_factory()
    _append_status_event(package, signer, "DISPUTE")
    _append_status_event(package, signer, "REVOCATION")
    # Mutable display fields are deliberately stale; only signed links decide.
    package["status"] = "ACTIVE"

    result = verify_package(package, expected_issuer_key_fingerprint=fingerprint)

    checks = _checks(result)
    assert checks["statement_lineage"]["result"] == "PASS"
    assert checks["lineage_binding"]["result"] == "PASS"
    assert result["derived_status"] == "REVOKED"
    assert result["valid"] is False
