from __future__ import annotations

import hashlib
import unittest

from creatorproof.client import ProofReceipt, VerificationPackage


class ProofReceiptTests(unittest.TestCase):
    def test_commitment_scope_alone_does_not_claim_a_blockchain(self) -> None:
        proof = ProofReceipt(
            anchor_status="ANCHORED",
            provider="example",
            commitment_scope="PUBLIC_EVM_ATTESTATION",
            packet_hash_sha256="ab" * 32,
        )
        self.assertFalse(proof.is_public_blockchain)

    def test_receipt_anchor_scope_identifies_public_chain(self) -> None:
        proof = ProofReceipt(
            anchor_status="ANCHORED",
            provider="ethereum-attestation-service",
            commitment_scope="CANONICAL_EVIDENCE_PACKET_EXCLUDING_PROOF_OBJECT",
            packet_hash_sha256="ab" * 32,
            receipt={"anchor_scope": "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY"},
        )
        self.assertTrue(proof.is_public_blockchain)

    def test_explorer_object_is_normalized_and_unsafe_url_is_ignored(self) -> None:
        proof = ProofReceipt(
            anchor_status="ANCHORED",
            provider="ethereum-attestation-service",
            commitment_scope=None,
            packet_hash_sha256=None,
            receipt={
                "explorer": {
                    "transaction_url": "https://example.test/tx/0x01",
                    "attestation_url": "https://example.test/attestation/0x02",
                    "attester_url": "javascript:alert(1)",
                }
            },
        )
        self.assertEqual(
            proof.explorer_urls,
            {
                "transaction": "https://example.test/tx/0x01",
                "attestation": "https://example.test/attestation/0x02",
            },
        )

    def test_pinned_fingerprint_is_computed_from_raw_bundled_key(self) -> None:
        public_key = bytes(range(32))
        expected = hashlib.sha256(public_key).hexdigest()
        package = VerificationPackage(
            {
                "signature": {"kid": "issuer-1"},
                "trust_bundle": {
                    "keys": [{"kid": "issuer-1", "public_key_hex": public_key.hex()}]
                },
            }
        )
        self.assertEqual(package.bundled_issuer_key_fingerprint_sha256, expected)
        self.assertTrue(package.matches_pinned_issuer_key(f"sha256:{expected}"))
        self.assertFalse(package.matches_pinned_issuer_key("00" * 32))


if __name__ == "__main__":
    unittest.main()
