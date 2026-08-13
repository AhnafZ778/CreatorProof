"""Fail-closed offline verifier for a CreatorProof evidence package.

The verifier needs no network, database, or third-party Python package.  Trust
does not come from the package's bundled key: callers must pin the issuer's raw
Ed25519 public-key fingerprint through an independent channel.

Besides the evidence-statement signature, strong verification requires:

* every record in the signed statement lineage to form one valid chain;
* a signed lineage binding that commits the ordered ids and digests;
* a signed transparency checkpoint; and
* an index-aware Merkle proof from the statement digest to that exact checkpoint.

The package's mutable ``status`` fields are deliberately ignored.  Current
status is derived only from the signed lineage and checked against the signed
lineage binding.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import cose, crypto_ed25519  # noqa: E402
from app.services.canonical import canonicalize  # noqa: E402
from app.services.transparency import leaf_hash, node_hash  # noqa: E402

OK = "PASS"
BAD = "FAIL"

_STATUS_FROM_EVENT = {
    "CORRECTION": "SUPERSEDED",
    "DISPUTE": "DISPUTED",
    "SUPERSESSION": "SUPERSEDED",
    "REVOCATION": "REVOKED",
}


def _unb64(value: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError("empty base64 value")
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _digest_hex(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 64:
        return None
    try:
        bytes.fromhex(value)
    except ValueError:
        return None
    return value.lower()


def _normalize_fingerprint(value: str | None) -> str:
    return str(value or "").strip().lower().removeprefix("sha256:")


def _trust_keys(package: dict) -> list[dict]:
    bundle = package.get("trust_bundle")
    if not isinstance(bundle, dict) or not isinstance(bundle.get("keys"), list):
        return []
    return [key for key in bundle["keys"] if isinstance(key, dict)]


def _trusted_key(
    package: dict,
    *,
    signature: dict,
    expected_fingerprint: str | None,
) -> tuple[dict | None, str]:
    kid = signature.get("kid")
    if not isinstance(kid, str) or not kid:
        return None, "MISSING_SIGNATURE_KID"

    expected = _normalize_fingerprint(expected_fingerprint)
    if _digest_hex(expected) is None:
        return None, "EXPECTED_ISSUER_KEY_FINGERPRINT_REQUIRED"

    matching = [key for key in _trust_keys(package) if key.get("kid") == kid]
    if len(matching) != 1:
        return None, f"KID_MUST_IDENTIFY_EXACTLY_ONE_BUNDLED_KEY:{kid}"
    key = matching[0]
    try:
        raw_key = bytes.fromhex(str(key.get("public_key_hex") or ""))
    except ValueError:
        return None, "INVALID_BUNDLED_PUBLIC_KEY"
    if len(raw_key) != 32:
        return None, "INVALID_BUNDLED_PUBLIC_KEY_LENGTH"

    actual = hashlib.sha256(raw_key).hexdigest()
    if actual != expected:
        return None, f"ISSUER_KEY_FINGERPRINT_MISMATCH:actual={actual} expected={expected}"

    deployment = package.get("deployment")
    declared = (
        deployment.get("issuer_key_fingerprint_sha256") if isinstance(deployment, dict) else None
    )
    if declared and _normalize_fingerprint(str(declared)) != expected:
        return None, "PACKAGE_ISSUER_FINGERPRINT_DISAGREES_WITH_EXTERNAL_PIN"

    algorithm = str(signature.get("alg") or key.get("algorithm") or "").lower()
    if algorithm not in {"ed25519", "eddsa"}:
        return None, f"UNSUPPORTED_ALGORITHM:{algorithm or 'missing'}"
    return key, f"kid={kid} fingerprint={actual}"


def _verify_raw_signature(
    package: dict,
    *,
    payload: dict,
    signature: dict,
    expected_fingerprint: str | None,
) -> tuple[bool, str, dict | None]:
    key, trust_detail = _trusted_key(
        package,
        signature=signature,
        expected_fingerprint=expected_fingerprint,
    )
    if key is None:
        return False, trust_detail, None
    try:
        canonical = canonicalize(payload)
        raw_signature = _unb64(signature.get("signature_b64"))
        if len(raw_signature) != 64:
            return False, "INVALID_ED25519_SIGNATURE_LENGTH", key
        expected_digest = signature.get("payload_digest_sha256")
        if (
            expected_digest is not None
            and _digest_hex(expected_digest) != hashlib.sha256(canonical).hexdigest()
        ):
            return False, "SIGNED_PAYLOAD_DIGEST_MISMATCH", key
        valid = crypto_ed25519.verify(
            bytes.fromhex(str(key["public_key_hex"])),
            cose.sig_structure(canonical, protected=cose.protected_header()),
            raw_signature,
        )
    except (KeyError, TypeError, ValueError) as exc:
        return False, f"INVALID_SIGNATURE_ENCODING:{type(exc).__name__}", key
    return valid, trust_detail if valid else "INVALID_ED25519_SIGNATURE", key


def _verify_cose_envelope(
    *, payload: dict, signature: dict, public_key: dict | None
) -> tuple[bool, str]:
    if public_key is None:
        return False, "NO_EXTERNALLY_TRUSTED_KEY"
    try:
        envelope = _unb64(signature.get("cose_sign1_b64"))
        _, envelope_end = cose.decode(envelope)
        parsed = cose.parse_sign1(envelope)
        canonical = canonicalize(payload)
        raw_signature = _unb64(signature.get("signature_b64"))
        protected_ok = parsed.get("protected") == cose.protected_header()
        kid_ok = parsed.get("kid") == signature.get("kid")
        payload_ok = parsed.get("payload") == canonical
        signature_ok = bytes(parsed.get("signature") or b"") == raw_signature
        envelope_ok = bool(envelope) and envelope[0] == 0xD2 and envelope_end == len(envelope)
        cryptographic_ok = crypto_ed25519.verify(
            bytes.fromhex(str(public_key["public_key_hex"])),
            cose.sig_structure(
                bytes(parsed.get("payload") or b""),
                protected=bytes(parsed.get("protected") or b""),
            ),
            bytes(parsed.get("signature") or b""),
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        return False, f"INVALID_COSE_SIGN1:{type(exc).__name__}"
    valid = (
        envelope_ok and protected_ok and kid_ok and payload_ok and signature_ok and cryptographic_ok
    )
    return (
        valid,
        (
            f"envelope={envelope_ok} protected={protected_ok} kid={kid_ok} payload={payload_ok} "
            f"signature={signature_ok} cryptographic={cryptographic_ok}"
        ),
    )


def _verify_signed_payload(
    package: dict,
    *,
    payload: dict,
    signature: dict,
    expected_fingerprint: str | None,
    require_cose: bool,
) -> tuple[bool, str]:
    raw_ok, raw_detail, key = _verify_raw_signature(
        package,
        payload=payload,
        signature=signature,
        expected_fingerprint=expected_fingerprint,
    )
    if not raw_ok:
        return False, raw_detail
    if not require_cose:
        return True, raw_detail
    cose_ok, cose_detail = _verify_cose_envelope(
        payload=payload,
        signature=signature,
        public_key=key,
    )
    return cose_ok, f"{raw_detail} cose=({cose_detail})"


def _check_digest(package: dict) -> dict:
    statement = package.get("statement")
    recorded = _digest_hex(package.get("payload_digest_sha256"))
    if not isinstance(statement, dict) or recorded is None:
        return {"name": "canonical_digest", "result": BAD, "detail": "MISSING_OR_INVALID"}
    try:
        computed = hashlib.sha256(canonicalize(statement)).hexdigest()
    except (binascii.Error, OverflowError, TypeError, UnicodeError, ValueError) as exc:
        return {
            "name": "canonical_digest",
            "result": BAD,
            "detail": f"CANONICALIZATION_FAILED:{type(exc).__name__}",
        }
    return {
        "name": "canonical_digest",
        "result": OK if computed == recorded else BAD,
        "detail": f"computed={computed} recorded={recorded}",
    }


def _check_signature(package: dict, *, expected_fingerprint: str | None) -> dict:
    statement = package.get("statement")
    signature = package.get("signature")
    if not isinstance(statement, dict) or not isinstance(signature, dict):
        return {"name": "signature", "result": BAD, "detail": "MISSING_SIGNATURE"}
    valid, detail, _ = _verify_raw_signature(
        package,
        payload=statement,
        signature=signature,
        expected_fingerprint=expected_fingerprint,
    )
    return {"name": "signature", "result": OK if valid else BAD, "detail": detail}


def _check_cose(package: dict, *, expected_fingerprint: str | None) -> dict:
    statement = package.get("statement")
    signature = package.get("signature")
    if not isinstance(statement, dict) or not isinstance(signature, dict):
        return {"name": "cose_sign1", "result": BAD, "detail": "MISSING_COSE_ENVELOPE"}
    _, _, key = _verify_raw_signature(
        package,
        payload=statement,
        signature=signature,
        expected_fingerprint=expected_fingerprint,
    )
    valid, detail = _verify_cose_envelope(
        payload=statement,
        signature=signature,
        public_key=key,
    )
    return {"name": "cose_sign1", "result": OK if valid else BAD, "detail": detail}


def _checkpoint_body(package: dict) -> tuple[dict | None, str]:
    transparency = package.get("transparency")
    if not isinstance(transparency, dict):
        return None, "MISSING_TRANSPARENCY_OBJECT"
    checkpoint = transparency.get("latest_checkpoint")
    log_id = transparency.get("log_id")
    if not isinstance(checkpoint, dict) or not isinstance(log_id, str) or not log_id:
        return None, "MISSING_SIGNED_CHECKPOINT"
    tree_size = checkpoint.get("tree_size")
    root = _digest_hex(checkpoint.get("root_sha256"))
    if (
        isinstance(tree_size, bool)
        or not isinstance(tree_size, int)
        or tree_size < 1
        or root is None
    ):
        return None, "INVALID_CHECKPOINT_BODY"
    return {"log_id": log_id, "tree_size": tree_size, "root_sha256": root}, ""


def _check_checkpoint_signature(package: dict, *, expected_fingerprint: str | None) -> dict:
    body, error = _checkpoint_body(package)
    if body is None:
        return {"name": "checkpoint_signature", "result": BAD, "detail": error}
    checkpoint = package["transparency"]["latest_checkpoint"]
    signature = {
        "alg": "Ed25519",
        "kid": checkpoint.get("signature_kid"),
        "signature_b64": checkpoint.get("signature_b64"),
    }
    valid, detail, _ = _verify_raw_signature(
        package,
        payload=body,
        signature=signature,
        expected_fingerprint=expected_fingerprint,
    )
    return {
        "name": "checkpoint_signature",
        "result": OK if valid else BAD,
        "detail": f"{detail} log_id={body['log_id']} tree_size={body['tree_size']}",
    }


def _verify_indexed_inclusion(
    *, leaf: bytes, leaf_index: int, tree_size: int, proof: list
) -> tuple[bool, bytes, str]:
    """Verify the path shape as well as its final root.

    Merely hashing arbitrary left/right siblings is insufficient: the claimed
    leaf index and tree size determine exactly where siblings must exist.
    """
    current = leaf
    index = leaf_index
    width = tree_size
    cursor = 0
    try:
        while width > 1:
            expected_side: str | None
            if index % 2 == 1:
                expected_side = "left"
            elif index + 1 < width:
                expected_side = "right"
            else:
                expected_side = None

            if expected_side is not None:
                if cursor >= len(proof) or not isinstance(proof[cursor], dict):
                    return False, current, "PROOF_TOO_SHORT"
                step = proof[cursor]
                if step.get("side") != expected_side:
                    return False, current, f"UNEXPECTED_PROOF_SIDE_AT_LEVEL:{cursor}"
                sibling_hex = _digest_hex(step.get("hash"))
                if sibling_hex is None:
                    return False, current, f"INVALID_SIBLING_HASH_AT_LEVEL:{cursor}"
                sibling = bytes.fromhex(sibling_hex)
                current = (
                    node_hash(sibling, current)
                    if expected_side == "left"
                    else node_hash(current, sibling)
                )
                cursor += 1
            index //= 2
            width = (width + 1) // 2
    except (TypeError, ValueError) as exc:
        return False, current, f"INVALID_PROOF:{type(exc).__name__}"
    if cursor != len(proof):
        return False, current, "PROOF_HAS_EXTRA_STEPS"
    return True, current, "PROOF_SHAPE_VALID"


def _check_transparency(package: dict) -> dict:
    transparency = package.get("transparency")
    checkpoint, checkpoint_error = _checkpoint_body(package)
    if not isinstance(transparency, dict) or checkpoint is None:
        return {
            "name": "transparency",
            "result": BAD,
            "detail": checkpoint_error or "MISSING_TRANSPARENCY_OBJECT",
        }

    committed = _digest_hex(transparency.get("packet_hash_sha256"))
    statement_digest = _digest_hex(package.get("payload_digest_sha256"))
    recorded_leaf = _digest_hex(transparency.get("leaf_hash_sha256"))
    leaf_index = transparency.get("leaf_index")
    tree_size = transparency.get("tree_size")
    root = _digest_hex(transparency.get("root_sha256"))
    proof = transparency.get("inclusion_proof")
    fields_ok = (
        committed is not None
        and committed == statement_digest
        and recorded_leaf is not None
        and isinstance(leaf_index, int)
        and not isinstance(leaf_index, bool)
        and 0 <= leaf_index < checkpoint["tree_size"]
        and isinstance(tree_size, int)
        and not isinstance(tree_size, bool)
        and tree_size == checkpoint["tree_size"]
        and root == checkpoint["root_sha256"]
        and isinstance(proof, list)
    )
    if not fields_ok:
        return {
            "name": "transparency",
            "result": BAD,
            "detail": "TRANSPARENCY_FIELDS_DO_NOT_MATCH_SIGNED_CHECKPOINT_OR_STATEMENT",
        }

    expected_leaf = leaf_hash(committed)
    leaf_ok = expected_leaf.hex() == recorded_leaf
    shape_ok, computed_root, proof_detail = _verify_indexed_inclusion(
        leaf=expected_leaf,
        leaf_index=leaf_index,
        tree_size=checkpoint["tree_size"],
        proof=proof,
    )
    inclusion_ok = shape_ok and computed_root.hex() == checkpoint["root_sha256"]
    return {
        "name": "transparency",
        "result": OK if leaf_ok and inclusion_ok else BAD,
        "detail": (
            f"leaf_hash_matches={leaf_ok} inclusion_matches_signed_checkpoint={inclusion_ok} "
            f"tree_size={tree_size} leaf_index={leaf_index} {proof_detail}"
        ),
    }


def _check_packet_binding(package: dict, *, expected_fingerprint: str | None) -> dict:
    binding = package.get("proof_binding")
    signature = package.get("proof_binding_signature")
    canonical_b64 = package.get("evidence_packet_canonical_b64")
    packet_object = package.get("evidence_packet_without_proof")
    if (
        not isinstance(binding, dict)
        or not isinstance(signature, dict)
        or not isinstance(canonical_b64, str)
        or not isinstance(packet_object, dict)
    ):
        return {"name": "packet_binding", "result": BAD, "detail": "MISSING_PACKET_BINDING"}
    try:
        packet_bytes = base64.b64decode(canonical_b64, validate=True)
        expected_bytes = json.dumps(
            packet_object,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        bytes_ok = packet_bytes == expected_bytes
        packet_ok = hashlib.sha256(packet_bytes).hexdigest() == _digest_hex(
            binding.get("packet_hash_sha256")
        )
        signature_ok, signature_detail = _verify_signed_payload(
            package,
            payload=binding,
            signature=signature,
            expected_fingerprint=expected_fingerprint,
            require_cose=True,
        )
    except (TypeError, ValueError) as exc:
        return {
            "name": "packet_binding",
            "result": BAD,
            "detail": f"INVALID_PACKET_BINDING:{type(exc).__name__}",
        }
    return {
        "name": "packet_binding",
        "result": OK if bytes_ok and packet_ok and signature_ok else BAD,
        "detail": (
            f"canonical_bytes_match={bytes_ok} packet_hash_matches={packet_ok} "
            f"issuer_signature_valid={signature_ok} {signature_detail}"
        ),
    }


def _check_lineage(package: dict, *, expected_fingerprint: str | None) -> tuple[dict, dict | None]:
    lineage = package.get("statement_lineage")
    if not isinstance(lineage, list) or not lineage:
        return {"name": "statement_lineage", "result": BAD, "detail": "MISSING_LINEAGE"}, None

    ids: list[str] = []
    digests: list[str] = []
    root_scan_id: str | None = None
    root_tenant_id: str | None = None
    previous_id: str | None = None
    previous_digest: str | None = None
    derived_status = "ACTIVE"

    for index, row in enumerate(lineage):
        if not isinstance(row, dict) or not isinstance(row.get("statement"), dict):
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"INVALID_LINEAGE_RECORD:{index}",
            }, None
        payload = row["statement"]
        statement_id = payload.get("statement_id")
        statement_type = payload.get("statement_type")
        payload_previous = payload.get("previous_statement_id")
        recorded_digest = _digest_hex(row.get("payload_digest_sha256"))
        if not isinstance(statement_id, str) or not statement_id or recorded_digest is None:
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"MISSING_ID_OR_DIGEST:{index}",
            }, None
        try:
            computed_digest = hashlib.sha256(canonicalize(payload)).hexdigest()
        except (TypeError, ValueError) as exc:
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"LINEAGE_CANONICALIZATION_FAILED:{index}:{type(exc).__name__}",
            }, None
        if computed_digest != recorded_digest:
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"LINEAGE_DIGEST_MISMATCH:{index}",
            }, None
        if statement_id in ids:
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"DUPLICATE_STATEMENT_ID:{statement_id}",
            }, None
        if (
            row.get("statement_type") != statement_type
            or row.get("previous_statement_id") != payload_previous
        ):
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"UNSIGNED_WRAPPER_DISAGREES_WITH_SIGNED_PAYLOAD:{index}",
            }, None
        if (
            payload.get("schema") != "creatorproof.statement.v2"
            or payload.get("issuer") != "creatorproof"
        ):
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"UNEXPECTED_SCHEMA_OR_ISSUER:{index}",
            }, None

        if index == 0:
            root_scan_id = payload.get("scan_id")
            root_tenant_id = payload.get("tenant_id")
            if statement_type != "RESULT" or payload_previous is not None:
                return {
                    "name": "statement_lineage",
                    "result": BAD,
                    "detail": "LINEAGE_ROOT_MUST_BE_RESULT_WITHOUT_PREDECESSOR",
                }, None
            if (
                canonicalize(payload) != canonicalize(package.get("statement"))
                or recorded_digest != _digest_hex(package.get("payload_digest_sha256"))
                or row.get("signature") != package.get("signature")
            ):
                return {
                    "name": "statement_lineage",
                    "result": BAD,
                    "detail": "PACKAGE_STATEMENT_DOES_NOT_EQUAL_LINEAGE_ROOT",
                }, None
        else:
            if statement_type not in _STATUS_FROM_EVENT:
                return {
                    "name": "statement_lineage",
                    "result": BAD,
                    "detail": f"INVALID_STATUS_EVENT_TYPE:{index}",
                }, None
            if (
                payload_previous != previous_id
                or payload.get("previous_payload_digest_sha256") != previous_digest
            ):
                return {
                    "name": "statement_lineage",
                    "result": BAD,
                    "detail": f"BROKEN_LINEAGE_LINK:{index}",
                }, None
            derived_status = _STATUS_FROM_EVENT[statement_type]

        if payload.get("scan_id") != root_scan_id or payload.get("tenant_id") != root_tenant_id:
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"LINEAGE_SCOPE_CHANGED:{index}",
            }, None
        signature = row.get("signature")
        if not isinstance(signature, dict):
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"MISSING_LINEAGE_SIGNATURE:{index}",
            }, None
        signature_ok, signature_detail = _verify_signed_payload(
            package,
            payload=payload,
            signature=signature,
            expected_fingerprint=expected_fingerprint,
            require_cose=True,
        )
        if not signature_ok:
            return {
                "name": "statement_lineage",
                "result": BAD,
                "detail": f"INVALID_LINEAGE_SIGNATURE:{index}:{signature_detail}",
            }, None

        ids.append(statement_id)
        digests.append(recorded_digest)
        previous_id = statement_id
        previous_digest = recorded_digest

    state = {
        "ids": ids,
        "digests": digests,
        "root_id": ids[0],
        "scan_id": root_scan_id,
        "derived_status": derived_status,
    }
    return {
        "name": "statement_lineage",
        "result": OK,
        "detail": f"records={len(ids)} links_valid=True signatures_valid=True",
    }, state


def _check_lineage_binding(
    package: dict,
    *,
    lineage_state: dict | None,
    expected_fingerprint: str | None,
) -> dict:
    binding = package.get("statement_lineage_binding")
    signature = package.get("statement_lineage_binding_signature")
    checkpoint, checkpoint_error = _checkpoint_body(package)
    if (
        lineage_state is None
        or checkpoint is None
        or not isinstance(binding, dict)
        or not isinstance(signature, dict)
    ):
        return {
            "name": "lineage_binding",
            "result": BAD,
            "detail": checkpoint_error or "MISSING_OR_UNVERIFIABLE_LINEAGE_BINDING",
        }

    fields_ok = (
        binding.get("schema") == "creatorproof.statement_lineage_binding.v1"
        and binding.get("scan_id") == lineage_state["scan_id"]
        and binding.get("root_statement_id") == lineage_state["root_id"]
        and binding.get("statement_ids") == lineage_state["ids"]
        and binding.get("payload_digests_sha256") == lineage_state["digests"]
        and binding.get("current_status") == lineage_state["derived_status"]
        and binding.get("checkpoint") == checkpoint
    )
    signature_ok, signature_detail = _verify_signed_payload(
        package,
        payload=binding,
        signature=signature,
        expected_fingerprint=expected_fingerprint,
        require_cose=True,
    )
    return {
        "name": "lineage_binding",
        "result": OK if fields_ok and signature_ok else BAD,
        "detail": (
            f"fields_match={fields_ok} issuer_signature_valid={signature_ok} "
            f"derived_status={lineage_state['derived_status']} {signature_detail}"
        ),
    }


def _status_note(lineage_state: dict | None) -> dict:
    status = lineage_state.get("derived_status") if lineage_state else "UNVERIFIABLE"
    current = status == "ACTIVE"
    return {
        "name": "derived_statement_status",
        "result": OK if current else ("ATTENTION" if lineage_state else BAD),
        "detail": (
            f"status={status} source=SIGNED_LINEAGE"
            + (
                " — the statement has a signed status successor and is not current."
                if lineage_state and not current
                else ""
            )
        ),
    }


def verify_package(package: dict, *, expected_issuer_key_fingerprint: str | None = None) -> dict:
    if not isinstance(package, dict):
        package = {}
    lineage_check, lineage_state = _check_lineage(
        package,
        expected_fingerprint=expected_issuer_key_fingerprint,
    )
    checks = [
        _check_digest(package),
        _check_signature(package, expected_fingerprint=expected_issuer_key_fingerprint),
        _check_cose(package, expected_fingerprint=expected_issuer_key_fingerprint),
        _check_checkpoint_signature(
            package,
            expected_fingerprint=expected_issuer_key_fingerprint,
        ),
        _check_transparency(package),
        _check_packet_binding(
            package,
            expected_fingerprint=expected_issuer_key_fingerprint,
        ),
        lineage_check,
        _check_lineage_binding(
            package,
            lineage_state=lineage_state,
            expected_fingerprint=expected_issuer_key_fingerprint,
        ),
        _status_note(lineage_state),
    ]
    valid = all(check["result"] == OK for check in checks)
    return {
        "schema": "creatorproof.offline_verification_result.v2",
        "valid": valid,
        "derived_status": lineage_state.get("derived_status") if lineage_state else None,
        "checks": checks,
        "verified_scope": (
            "This verifies an externally pinned issuer signature, the complete signed "
            "statement lineage, and inclusion in that issuer's signed checkpoint. It does "
            "not independently query a blockchain, establish legal ownership, or prove "
            "that an evidence claim is true."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a CreatorProof evidence statement offline and fail closed."
    )
    parser.add_argument("package", type=Path, help="Verification package JSON file.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--expected-issuer-key-sha256",
        required=True,
        help=(
            "SHA-256 of the raw 32-byte Ed25519 issuer public key, obtained from an "
            "independent deployment channel."
        ),
    )
    args = parser.parse_args()

    package = json.loads(args.package.read_text(encoding="utf-8"))
    if isinstance(package.get("verification_package"), dict):
        package = package["verification_package"]
    result = verify_package(
        package,
        expected_issuer_key_fingerprint=args.expected_issuer_key_sha256,
    )

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Statement verification: {'VALID' if result['valid'] else 'INVALID'}")
        for check in result["checks"]:
            print(f"  [{check['result']:>9}] {check['name']}: {check['detail']}")
        print(f"\n{result['verified_scope']}")
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
