import hashlib

from app.domain.enums import AnchorStatus
from app.providers.proof import MerkleTransparencyAnchor, verify_merkle_receipt


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_merkle_transparency_receipt_is_verifiable_and_tamper_evident(tmp_path):
    anchor = MerkleTransparencyAnchor(tmp_path / "proof-log.jsonl")
    first = anchor.anchor(_hash("first packet"))
    second_hash = _hash("second packet")
    second = anchor.anchor(second_hash)

    assert first.status == AnchorStatus.ANCHORED
    assert second.status == AnchorStatus.ANCHORED
    assert second.receipt is not None
    assert second.receipt["anchor_scope"] == "LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN"
    assert verify_merkle_receipt(
        second_hash,
        second.receipt["root_sha256"],
        second.receipt["inclusion_proof"],
    )
    assert not verify_merkle_receipt(
        _hash("tampered packet"),
        second.receipt["root_sha256"],
        second.receipt["inclusion_proof"],
    )


def test_invalid_merkle_receipt_input_fails_closed():
    assert not verify_merkle_receipt("not-hex", "also-not-hex", [])
