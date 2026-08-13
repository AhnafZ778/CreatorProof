"""Ed25519, COSE_Sign1, and the append-only transparency log."""

import hashlib

import pytest

from app.services import cose, crypto_ed25519
from app.services.transparency import compute_root, leaf_hash, node_hash, verify_inclusion

# RFC 8032 section 7.1 test vectors. A pure-Python implementation is only
# trustworthy if it reproduces the published ones exactly.
RFC_8032_VECTORS = [
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e3970"
        "1cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613"
        "d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760"
        "984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]


@pytest.mark.parametrize(("seed", "public_key", "message", "signature"), RFC_8032_VECTORS)
def test_matches_rfc_8032_vectors(seed, public_key, message, signature):
    seed_bytes = bytes.fromhex(seed)
    derived = crypto_ed25519.public_key_from_seed(seed_bytes)
    assert derived.hex() == public_key
    produced = crypto_ed25519.sign(seed_bytes, bytes.fromhex(message))
    assert produced.hex() == signature
    assert crypto_ed25519.verify(derived, bytes.fromhex(message), produced)


def test_verification_rejects_a_tampered_message():
    seed = crypto_ed25519.generate_seed()
    public_key = crypto_ed25519.public_key_from_seed(seed)
    signature = crypto_ed25519.sign(seed, b"original")
    assert crypto_ed25519.verify(public_key, b"original", signature)
    assert not crypto_ed25519.verify(public_key, b"0riginal", signature)


def test_verification_rejects_another_keys_signature():
    seed_a, seed_b = crypto_ed25519.generate_seed(), crypto_ed25519.generate_seed()
    signature = crypto_ed25519.sign(seed_a, b"payload")
    assert not crypto_ed25519.verify(
        crypto_ed25519.public_key_from_seed(seed_b), b"payload", signature
    )


def test_cose_sign1_round_trip_preserves_payload_and_kid():
    payload = b'{"a":1}'
    envelope = cose.build_sign1(payload=payload, signature=b"\x01" * 64, kid="key-1")
    parsed = cose.parse_sign1(envelope)
    assert parsed["payload"] == payload
    assert parsed["kid"] == "key-1"
    assert bytes(parsed["signature"]) == b"\x01" * 64
    assert parsed["protected"] == cose.protected_header()


def test_sig_structure_is_the_signature1_array():
    structure = cose.sig_structure(b"body", protected=cose.protected_header())
    decoded, _ = cose.decode(structure)
    assert decoded[0] == "Signature1"
    assert decoded[3] == b"body"


def test_merkle_leaf_and_node_hashes_are_domain_separated():
    packet = hashlib.sha256(b"packet").hexdigest()
    assert leaf_hash(packet) == hashlib.sha256(b"\x00" + bytes.fromhex(packet)).digest()
    assert (
        node_hash(b"\x01" * 32, b"\x02" * 32)
        == hashlib.sha256(b"\x01" + b"\x01" * 32 + b"\x02" * 32).digest()
    )


def test_single_leaf_root_is_the_leaf_itself():
    packet = hashlib.sha256(b"only").hexdigest()
    assert compute_root([leaf_hash(packet)]) == leaf_hash(packet)
    assert verify_inclusion(packet, leaf_hash(packet).hex(), [])


def test_inclusion_proof_fails_against_a_foreign_root():
    packet = hashlib.sha256(b"claimed").hexdigest()
    other = hashlib.sha256(b"other").hexdigest()
    assert not verify_inclusion(packet, leaf_hash(other).hex(), [])


def test_inclusion_proof_rejects_a_malformed_proof_step():
    packet = hashlib.sha256(b"claimed").hexdigest()
    assert not verify_inclusion(packet, leaf_hash(packet).hex(), [{"side": "left"}])
