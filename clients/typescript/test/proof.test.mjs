import assert from "node:assert/strict";
import test from "node:test";

import { isPublicBlockchainProof, proofExplorerLinks } from "../dist/index.js";

test("commitment scope alone never claims a blockchain", () => {
  assert.equal(
    isPublicBlockchainProof({ commitment_scope: "PUBLIC_EVM_ATTESTATION" }),
    false,
  );
});

test("receipt anchor scope identifies a public EAS proof", () => {
  assert.equal(
    isPublicBlockchainProof({
      commitment_scope: "CANONICAL_EVIDENCE_PACKET_EXCLUDING_PROOF_OBJECT",
      receipt: { anchor_scope: "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY" },
    }),
    true,
  );
});

test("structured explorer URLs are normalized and unsafe schemes are rejected", () => {
  assert.deepEqual(
    proofExplorerLinks({
      receipt: {
        explorer: {
          transaction_url: "https://sepolia.etherscan.io/tx/0x01",
          attestation_url: "https://sepolia.easscan.org/attestation/view/0x02",
          attester_url: "javascript:alert(1)",
        },
      },
    }),
    [
      { kind: "transaction", url: "https://sepolia.etherscan.io/tx/0x01" },
      { kind: "attestation", url: "https://sepolia.easscan.org/attestation/view/0x02" },
    ],
  );
});
