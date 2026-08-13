# CreatorProof local blockchain (olympiad demo)

Runs a local EVM (Ganache) with EAS-compatible contracts so CreatorProof can
anchor evidence packet hashes, checkpoint roots and counterparty co-attestations
without a public faucet.

## Quick start

```bash
# terminal 1 — local chain
cd creatorproof/blockchain-local
npm install
npm run chain

# terminal 2 — deploy schemas/contracts (once per fresh chain)
node deploy.mjs
# then sync the printed values into apps/api/.env

# terminal 3 — API
cd creatorproof/apps/api
uv run --no-sync uvicorn "app.main:app" --host 127.0.0.1 --port 8000
```

## What gets deployed

| Contract / schema | Purpose |
| --- | --- |
| `SchemaRegistry`, `EAS` | Minimal EAS-compatible pair so the production code path runs unchanged |
| `bytes32 packetHash` (revocable) | Direct evidence-packet attestation |
| `bytes32 checkpointHash` (non-revocable) | Batched transparency-checkpoint attestation |
| `bytes32 coAttestationHash` (revocable) | Counterparty co-attestation; a member may withdraw its own commitment |
| `CreatorProofMemberRegistry` | Who may co-attest: address, role, status, two-step governor transfer, regulator observer |
| `CreatorProofClearanceReceipt` | Non-transferable (ERC-5192 `locked`) receipt for a completed clearance check |

`deploy.mjs` writes `deployment.json` and enrols the deploying attester as a
`PLATFORM` member. Enrol counterparties with `enroll(address, orgId, role)` from
the governor account; role codes are `1..7` in the order `PLATFORM`, `CREATOR`,
`AGENCY`, `BRAND`, `MARKETPLACE`, `REVIEWER`, `REGULATOR_OBSERVER`.

Map `deployment.json` onto settings as follows:

| deployment.json | Setting |
| --- | --- |
| `eas` | `CREATORPROOF_EAS_CONTRACT_ADDRESS` |
| `registry` | `CREATORPROOF_EAS_SCHEMA_REGISTRY_ADDRESS` |
| `packetSchemaUid` | `CREATORPROOF_EAS_SCHEMA_UID` |
| `checkpointSchemaUid` | `CREATORPROOF_EAS_CHECKPOINT_SCHEMA_UID` |
| `coAttestationSchemaUid` | `CREATORPROOF_EAS_COATTESTATION_SCHEMA_UID` |
| `memberRegistry` | `CREATORPROOF_EAS_MEMBER_REGISTRY_ADDRESS` |
| `clearanceReceipt` | `CREATORPROOF_EAS_CLEARANCE_RECEIPT_ADDRESS` |
| `attester` | `CREATORPROOF_EAS_REQUIRED_ATTESTER_ADDRESS` |
| `easCodeSha256` | `CREATORPROOF_EAS_EXPECTED_CONTRACT_CODE_SHA256` |

Proof mode should be:

- `CREATORPROOF_PROOF_ANCHOR_MODE=eas`
- `CREATORPROOF_PROOF_REQUIRE_CHAIN=true`
- RPC `http://127.0.0.1:8545`, chain id `31337`

Then confirm the deployment is genuinely chain-backed:

```bash
uv run --no-sync python -m scripts.competition_preflight
uv run --no-sync python -m scripts.blockchain_acceptance
```

This is a development harness. It is not a public chain, it has no independent
validator set, and a demo must never present it as one; `eas_network_label`
should say so. Only 32-byte hashes go on-chain here as well — media, identity
and decision text stay off-chain.
