# Blockchain implementation and deployment runbook

Status: implementation contract and operator runbook, checked 2026-08-12.

This document defines where CreatorProof deliberately uses a public blockchain,
where it deliberately does not, how to activate the current EAS integration, and
how to evolve from competition-scale direct writes to cost-efficient production
batching. It is an operational contract: a deployment is not allowed to call
itself blockchain-enabled until the acceptance checks in section 8 pass.

## 1. Architecture decision

CreatorProof uses Ethereum Attestation Service (EAS) on an EVM network as an
independent timestamp and commitment witness. EAS is used because a creator,
publisher, reviewer and CreatorProof may not trust one another's database clock.
It is not used as storage, a copyright oracle, a token, or a payment rail.

Two anchoring paths serve different latency and cost requirements:

| Path | Events | Chain unit | Purpose |
| --- | --- | --- | --- |
| Direct packet anchor | Completed scan evidence packets | One EAS attestation per packet | Immediate, simple public proof for the competition prototype and high-value cases |
| Batched checkpoint anchor | Work registrations plus rights, dispute, correction, revocation and supersession statements | One EAS attestation per signed Merkle checkpoint | Complete lifecycle coverage without paying for one transaction per business event |
| Counterparty co-attestation | A brand, agency, marketplace or creator committing to a clearance result | One EAS attestation per signed commitment, `refUID` → the platform attestation | Turns a single-vendor timestamp into a multi-party record that CreatorProof alone could not have produced |

The direct path is retained for the BCOL demonstration. The checkpoint path is
the production default once its worker and verifier are promoted. A deployment
may use both: direct proof for a completed scan and batched proof for its wider
business history.

The third path exists because the first two are all signed by CreatorProof's own
key. They prove *when* a packet existed; they cannot prove that anybody else
accepted it. Membership lives in a separate registry contract so a reviewer can
check whether the signing address was an active member at the time without
asking CreatorProof.

### What must never be claimed

An attestation proves that a specific commitment existed no later than the block
containing it and that a particular EVM account submitted it. It does not prove
originality, ownership, authorship, legality, detector accuracy, or the identity
of the person controlling that account.

## 2. Purposeful feature mapping

| Feature or datum | Public chain? | Design |
| --- | --- | --- |
| Completed evidence packet | Yes, direct for the demo/high-value tier | Attest the SHA-256 hash of the canonical packet without its proof object |
| Work registration | Yes, batched | Append a signed registration statement to the transparency tree; anchor the checkpoint containing it |
| Rights claim or licence status | Yes, batched | Anchor signed state-transition statements, never mutable database rows |
| Dispute, correction, supersession, revocation | Yes, batched | Append a new event; preserve and continue to verify the original event |
| AI score, vector, perceptual hash, matched regions | No | Keep inside the canonical off-chain evidence packet; the packet commitment covers them |
| Media bytes and derived crops | No | Object storage with deletion/retention policy; never publish personal or commercially sensitive media |
| Creator/customer identity | No | Tenant-scoped database and credentials; the chain is not an identity provider |
| Authorization and policy decisions | No execution on chain | Evaluate in the policy service, then commit the signed outcome through the event log |
| Counterparty decision on a clearance result | Yes, as a hash | Attest `SHA-256` of the counterparty's canonical signed body; the body, the note and the party name stay off chain |
| Network membership, role and status | Yes | `CreatorProofMemberRegistry` holds address, role code, status code and timestamps; the display name and organization stay in `network_members` |
| Clearance receipt token | Yes, non-transferable | `CreatorProofClearanceReceipt` binds a `packetHash` and attestation UID to a holder. It represents a completed check, explicitly not ownership of the work |
| Payment or royalty settlement | No, unless a later multi-party settlement requirement is proven | Do not add a token or payment contract merely to increase blockchain surface area |

## 3. Commitment contracts

### Direct evidence-packet schema

Register this EAS schema exactly:

```text
bytes32 packetHash
```

Use no resolver and set `revocable=true`. The value is:

```text
packetHash = SHA-256(CREATORPROOF_SORTED_JSON_ASCII_V1(evidence_packet_without_proof))
```

Evidence Packet v1 predates the statement format and does **not** use JCS. The
verification package therefore carries the exact canonical bytes as
`evidence_packet_canonical_b64`; cross-runtime verifiers hash those bytes rather
than attempting to reproduce Python number formatting. Signed statements and
`proof_binding` use RFC 8785 JCS. The verification package must contain the
canonical packet, `proof_binding`, and
deployment fingerprints. A verifier must recompute the hash and compare the full
attestation record: UID, data, schema UID, attester, recipient, chain ID, EAS
contract, revocation/expiration state and transaction/block inclusion. Checking
only `isAttestationValid(uid)` is insufficient.

### Batched checkpoint schema

Use a separate EAS schema so a checkpoint can never be confused with a packet:

```text
bytes32 checkpointHash
```

Use no resolver and set `revocable=false`. A checkpoint is immutable history;
corrections and revocations are later leaves rather than mutations of the root.

The committed value is the Merkle checkpoint's 32-byte `root_sha256`. The
checkpoint body signed by the separately trusted Ed25519 issuer is:

```text
log_id          stable transparency-log identifier
tree_size       number of committed leaves
root_sha256     RFC 6962-style Merkle root at tree_size; this is the EAS value
```

The stored/exported envelope adds `signature_kid` and `signature_b64`. Its proof
package also carries an independently checked deployment fingerprint covering
chain ID, EAS contract, schema UID and required attester. Each exported event
proof contains the signed event, its Merkle inclusion path, the signed checkpoint,
and its EAS receipt. Verification therefore has four independent gates: event
signature, Merkle inclusion, checkpoint signature, and on-chain root binding.

### Counterparty co-attestation schema

Register a third EAS schema, again distinct so the three commitment kinds can
never be confused for one another:

```text
bytes32 coAttestationHash
```

Use no resolver and set `revocable=true`, because a member may withdraw its own
commitment. The committed value is the canonical digest of the signed body:

```text
coAttestationHash = SHA-256(JCS(counterparty_attestation_body))
```

The body has exactly these fields, and a submission whose body has any other
shape is refused rather than normalized:

```text
schema, chain_id, verifying_contract, deployment_id, scan_id,
packet_hash_sha256, platform_attestation_uid, party_org_id, party_role,
decision, decision_note_sha256, signer_address, issued_at, nonce
```

The counterparty signs the EIP-712 struct `CounterpartyAttestation(bytes32
bodyHash)` under a domain that pins `chainId` and the member registry as
`verifyingContract`, so a signature collected for one deployment cannot be
replayed against another network or another registry. CreatorProof recovers the
address, compares it with `signer_address`, checks the registry, and only then
submits the attestation with `refUID` set to the platform attestation UID.

Verification therefore has five gates: the recovered EVM address, the membership
record at signing time, the recomputed body digest, the on-chain committed value,
and the `refUID` binding back to the packet attestation.

### Batch policy

`CREATORPROOF_TRANSPARENCY_CHECKPOINT_INTERVAL=1` is suitable for a deterministic
competition demo: every event advances the checkpoint. Production should combine
an event threshold with a time flush, for example 100 events or 60 seconds,
whichever happens first. Exactly one worker must atomically claim each contiguous
unanchored range; retries reuse the checkpoint idempotency key and never create a
different root for the same tree size.

## 4. Base Sepolia reference deployment

The repository's safe example targets Base Sepolia:

| Setting | Value |
| --- | --- |
| Network | Base Sepolia |
| Chain ID | `84532` |
| Development RPC | `https://sepolia.base.org` |
| EAS | `0x4200000000000000000000000000000000000021` |
| Schema Registry | `0x4200000000000000000000000000000000000020` |
| Block explorer | `https://sepolia-explorer.base.org` |
| EAS scanner | `https://base-sepolia.easscan.org` |

The RPC is public and rate-limited. It is appropriate for health checks and a
small demo, not production. The chain, contract and explorer values are public
configuration, not secrets. Sources: [Base network configuration](https://docs.base.org/base-chain/quickstart/connecting-to-base),
[official EAS deployments](https://github.com/ethereum-attestation-service/eas-contracts#deployments),
and [EAS schema documentation](https://docs.attest.org/docs/tutorials/create-a-schema).

## 5. One-time testnet provisioning

1. Create two independent keys in an approved secret store:
   an Ed25519 statement key and a secp256k1 EVM attester key. For the competition
   demo, a disposable testnet-only EVM account is acceptable. Never reuse a
   personal wallet, never commit the key, and never place it in a command line.
2. Record the attester address before funding it. Fund only that address with a
   small amount of Base Sepolia ETH using a provider listed in the
   [official Base faucet directory](https://docs.base.org/base-chain/network-information/network-faucets).
3. On `https://base-sepolia.easscan.org`, register `bytes32 packetHash` with no
   resolver and `revocable=true`. Record the schema transaction and UID.
4. For checkpoint batching, separately register `bytes32 checkpointHash` with no
   resolver and `revocable=false`. Never reuse the packet schema UID.
5. For multi-party attestation, register `bytes32 coAttestationHash` with no
   resolver and `revocable=true`, then deploy `CreatorProofMemberRegistry` and
   `CreatorProofClearanceReceipt` from
   `blockchain-local/contracts/CreatorProofNetwork.sol`. Enrol the platform
   attester with role `PLATFORM`, then enrol each counterparty address with its
   own role. On a shared deployment, transfer the registry governor to an account
   that is not the attester immediately after provisioning; the transfer is
   two-step, so the new governor must call `acceptGovernance`.
6. Independently verify all three schema records on the EAS scanner. Confirm
   exact spelling, field type, resolver and revocability before putting a UID
   into a deployment secret.
7. For Compose, copy the repository-root `.env.example` to the ignored root
   `.env`; for a native API process, copy it to `apps/api/.env`. A competition
   deployment can start from `.env.competition.example`, which is already
   fail-closed. Supply both private keys, all three schema UIDs, both contract
   addresses, the pinned attester and the independently computed issuer-key
   fingerprint through the local secret mechanism. Keep
   `CREATORPROOF_PROOF_ANCHOR_MODE=eas` and
   `CREATORPROOF_PROOF_REQUIRE_CHAIN=true` for the competition deployment.
8. Build and start the backend with the locked blockchain extra:

   ```bash
   docker compose build api worker
   docker compose up -d postgres redis api worker
   ```

9. Read the non-secret issuer/deployment fingerprints from the accepted backend
   trust/status output and compare them with the independently calculated values.
   Put the accepted values into the three `NEXT_PUBLIC_CREATORPROOF_*` settings.
   Publish the same values in the competition paper or another channel the API
   cannot rewrite.
10. Build the web image only after those public pins are set, because Next.js
   statically embeds `NEXT_PUBLIC_*` values:

   ```bash
   docker compose build web
   docker compose up -d web
   ```

The official image already includes `web3`, `eth-abi`, and `eth-account`; never
install dependencies inside a running container. A web build with blank pins can
check package self-consistency but must not display an independently trusted state.

## 6. Configuration contract

| Variable | Required for chain | Rule |
| --- | --- | --- |
| `CREATORPROOF_PROOF_ANCHOR_MODE` | Yes | `eas` makes incomplete EAS setup visibly fail; `auto` may fall back to local transparency |
| `CREATORPROOF_PROOF_REQUIRE_CHAIN` | Competition/strict deployments | `true` forbids local fallback; there is no `chain_required` mode value |
| `CREATORPROOF_EAS_RPC_URL` | Yes | Dedicated HTTPS RPC in production; never expose an RPC credential to the browser |
| `CREATORPROOF_EAS_RPC_URLS_JSON` | Recommended | Ordered JSON array for failover; the single URL is prepended if absent |
| `CREATORPROOF_EAS_CHAIN_ID` | Recommended | Must equal `eth_chainId`; change it with the whole network tuple |
| `CREATORPROOF_EAS_CONTRACT_ADDRESS` | Yes | Pin the official EAS deployment and verify non-empty bytecode at startup |
| `CREATORPROOF_EAS_EXPECTED_CONTRACT_CODE_SHA256` | Production | Pin SHA-256 of the independently verified runtime bytecode |
| `CREATORPROOF_EAS_SCHEMA_REGISTRY_ADDRESS` | Recommended | Pin the official registry rather than discovering a caller-controlled address |
| `CREATORPROOF_EAS_SCHEMA_UID` | Yes | Pin the exact packet schema; do not accept a caller-selected schema |
| `CREATORPROOF_EAS_SCHEMA_DEFINITION` | Yes | Must be exactly `bytes32 packetHash` for direct scan proof |
| `CREATORPROOF_EAS_CHECKPOINT_SCHEMA_UID` | Lifecycle batching | Separate, non-revocable checkpoint schema; required when domain anchoring is enabled |
| `CREATORPROOF_EAS_CHECKPOINT_SCHEMA_DEFINITION` | Lifecycle batching | Must be exactly `bytes32 checkpointHash` |
| `CREATORPROOF_EAS_PRIVATE_KEY` | Current signer only | Secret, dedicated and minimally funded; never log or include in receipts |
| `CREATORPROOF_EAS_REQUIRED_ATTESTER_ADDRESS` | Strict deployments | Public address derived independently from the signer and pinned in the trust manifest |
| `CREATORPROOF_EAS_RECIPIENT` | Yes | Zero address means an unassigned public commitment; otherwise pin a documented recipient policy |
| `CREATORPROOF_EAS_REQUIRED_CONFIRMATIONS` | Yes | Minimum canonical block-depth gate; it is not called protocol finality |
| `CREATORPROOF_EAS_FINALITY_POLICY` | Yes | `safe` or `finalized` in production; jobs remain pending and reconcile until the selected RPC tag covers the attestation block |
| `CREATORPROOF_EAS_MAX_FEE_PER_GAS_GWEI` | Mainnet | Nonzero cost circuit breaker; `0` disables it |
| `CREATORPROOF_EAS_MAX_ATTEMPTS` | Yes | Retry only errors known to be transient; preserve a sent transaction hash |
| `CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX` | Yes | Independent Ed25519 secret; never derive from a published development value |
| `CREATORPROOF_STATEMENT_SIGNING_KID` | Yes | Stable public key identifier recorded in signed envelopes |
| `CREATORPROOF_TRUSTED_ISSUER_KEY_SHA256` | Strict deployments | Fingerprint published outside proof packages and checked against the active issuer |
| `NEXT_PUBLIC_CREATORPROOF_ISSUER_KEY_FINGERPRINT_SHA256` | Trusted web verifier | Public copy of the independently published issuer-key fingerprint, injected at web build time |
| `NEXT_PUBLIC_CREATORPROOF_DEPLOYMENT_FINGERPRINT_SHA256` | Trusted web verifier | Public pin for chain ID, contract, schemas and required attester, injected at web build time |
| `NEXT_PUBLIC_CREATORPROOF_ISSUER` | Trusted web verifier | Expected statement issuer; defaults to `creatorproof` |
| `CREATORPROOF_TRANSPARENCY_CHECKPOINT_INTERVAL` | Batching | Event threshold; pair with a time flush in the batch worker |
| `CREATORPROOF_TRANSPARENCY_CHECKPOINT_MAX_AGE_SECONDS` | Batching | Maximum age of the oldest leaf in a trailing partial batch before a signed checkpoint is flushed |
| `CREATORPROOF_BLOCKCHAIN_DOMAIN_ANCHORING_ENABLED` | Lifecycle batching | Enqueues completed signed checkpoints for EAS; disabling it stops new lifecycle anchors |
| `CREATORPROOF_BLOCKCHAIN_DISPATCH_INTERVAL_SECONDS` | Lifecycle batching | Poll interval for durable pending/reconciliation work |
| `CREATORPROOF_BLOCKCHAIN_ANCHOR_LEASE_SECONDS` | Lifecycle batching | Crash-recovery lease; longer than one expected submission/reconciliation attempt |
| `CREATORPROOF_BLOCKCHAIN_ANCHOR_MAX_ATTEMPTS` | Lifecycle batching | Durable retry ceiling before operator intervention |
| `CREATORPROOF_BLOCKCHAIN_ANCHOR_RETRY_BACKOFF_SECONDS` | Lifecycle batching | Base for capped exponential retry delay |
| `CREATORPROOF_BLOCKCHAIN_COUNTERPARTY_ATTESTATION_ENABLED` | Multi-party | Enables the co-attestation lane; when on, its schema and registry become mandatory in production |
| `CREATORPROOF_EAS_COATTESTATION_SCHEMA_UID` | Multi-party | Third, revocable schema; never reuse the packet or checkpoint UID |
| `CREATORPROOF_EAS_COATTESTATION_SCHEMA_DEFINITION` | Multi-party | Must be exactly `bytes32 coAttestationHash` |
| `CREATORPROOF_EAS_MEMBER_REGISTRY_ADDRESS` | Multi-party | Registry contract; also the EIP-712 `verifyingContract` that binds a signature to this deployment |
| `CREATORPROOF_EAS_CLEARANCE_RECEIPT_ADDRESS` | Optional | Soulbound receipt contract; issuance is an operator action, not an API pipeline |
| `CREATORPROOF_COUNTERPARTY_ATTESTATION_DOMAIN_NAME` | Multi-party | EIP-712 domain name; changing it invalidates previously collected signatures |
| `CREATORPROOF_COUNTERPARTY_ATTESTATION_DOMAIN_VERSION` | Multi-party | EIP-712 domain version; bump only with a documented migration |
| `CREATORPROOF_COUNTERPARTY_ATTESTATION_MAX_AGE_SECONDS` | Multi-party | Acceptance window for a collected signature; bounds third-party replay |
| `CREATORPROOF_COUNTERPARTY_MEMBERSHIP_REQUIRED` | Multi-party | `true` refuses any address the registry does not report `ACTIVE`, including when the registry cannot be read |

Compose forwards every current setting to both the API and worker because the
existing provider requires the private key even to initialize read operations.
This is a transitional limitation, not the target custody model.

## 7. Signer custody boundary

### Competition/testnet boundary

- Use a unique testnet-only EOA with only enough ETH for the demonstration.
- Inject its key at container start from the host/CI secret store.
- Redact `eas_private_key`, RPC credentials and statement keys from structured
  logs, exception messages, diagnostics and exported proof packages.
- Serialize nonce allocation for every process sharing the account.

### Production boundary

Replace the raw-key field with a `ChainSigner` interface owned by a dedicated
proof worker:

```text
address() -> checksum address
sign_or_send(unsigned_transaction, idempotency_key) -> transaction hash
health() -> signer availability without secret material
```

Implementations may use AWS KMS, Google Cloud KMS, Azure Key Vault, HashiCorp
Vault, an HSM, or a managed relayer. The API and verifier receive only the
attester address and trusted deployment manifest. They must never need signing
authority. The signer service enforces allowed chain, EAS contract, schema,
zero-value transactions, gas ceiling, rate limit and idempotency key. A database
nonce lease or one-writer queue prevents concurrent nonce collisions.

## 8. Deployment acceptance gate

Run these checks before a demo and retain the non-secret outputs as an acceptance
artifact:

1. Run the readiness check first. It fails closed on configuration *and* on live
   chain state, so it answers "will the next write go to a chain" before any
   transaction exists:

   ```bash
   docker compose exec api uv run --no-sync python -m scripts.competition_preflight
   ```

2. Run the fail-closed acceptance command. It exits successfully only after it
   live-reconciles a direct packet attestation, a batched checkpoint attestation
   and, when the multi-party lane is enabled, a counterparty co-attestation whose
   `refUID` binds back to the packet attestation:

   ```bash
   docker compose exec api uv run --no-sync python -m scripts.blockchain_acceptance
   ```

3. `docker compose config` contains no literal private key and resolves the
   expected chain ID, EAS address and schema UID.
4. `docker compose exec api uv run --no-sync python -c "import web3, eth_abi, eth_account"`
   exits zero.
5. `GET /readyz` and `GET /v1/proof/status` identify EAS, Base Sepolia, chain
   `84532`, the pinned contract/schema/attester, and no local-blockchain ambiguity.
6. `GET /v1/proof/preflight` verifies RPC connectivity, matching chain ID,
   deployed contract bytecode, exact schema record and nonzero signer balance.
7. Submit one known evidence packet. Require transaction status 1, an EAS UID,
   the configured confirmation threshold and working explorer links.
8. Export the verification package. Recompute the packet hash without trusting
   the API, fetch the full EAS attestation, and compare every binding.
9. Change one byte of the packet and require verification to fail.
10. Supply a valid but unrelated EAS UID and require verification to fail.
11. Revoke the demo attestation and require verification to report revoked.
12. Restart the API and worker and reverify the original package. Proof must not
    depend on process memory.
13. For checkpoint mode, create registration and rights-status events, wait for
    a flush, and verify each event's inclusion in the publicly anchored root.
14. For the multi-party lane, `GET /v1/network/status` must report
    `accepting_signatures` and a readable registry. Collect one co-attestation
    through `POST /v1/network/co-attestations/challenge` and
    `POST /v1/network/co-attestations`, then require that its detail view shows
    `on_chain_commitment_matches_body_hash` and
    `on_chain_ref_uid_matches_platform_attestation`.
15. Re-sign the same body with a key that is not enrolled and require refusal;
    edit one field of a signed body and require refusal. Both must fail before
    any transaction is created.

Confirmation depth demonstrates canonical L2 inclusion but is not protocol
finality. Competition and production deployments use the configured `safe` or
`finalized` RPC view, retain the receipt block hash, and continuously reconcile
it. Base documents the distinction in its
[transaction finality guidance](https://docs.base.org/base-chain/network-information/transaction-finality).

## 9. Monitoring and cost controls

Alert on:

- signer balance below the configured runway;
- pending submission age above the receipt timeout;
- nonce conflicts, replaced or dropped transactions;
- receipt block-hash changes and confirmation regression;
- schema/contract/chain mismatch;
- counterparty attestations stuck in `SIGNED` (a signature collected but never
  anchored) and registry reads failing, since an unreadable registry refuses
  every new co-attestation;
- checkpoint backlog age and number of unanchored leaves;
- EAS validation, revocation or expiration failure;
- gas price above policy and daily gas spend above budget;
- RPC disagreement when redundant providers return different chain heads.

Record transaction hash, UID, chain ID, block number/hash, schema, attester,
recipient, committed hash, fee, attempt count and confirmation/finality state.
Never record the private key, raw RPC credentials, or private evidence payload.

## 10. Rollout and rollback

### Rollout

1. Deploy the locked image with `auto`, `PROOF_REQUIRE_CHAIN=false`, and testnet
   credentials; compare local and EAS verification in shadow operation.
2. Pass section 8 and a signer rotation/reorg/RPC-outage drill.
3. Switch the competition environment to `eas` plus
   `PROOF_REQUIRE_CHAIN=true`. A chain failure must be visible, never silently
   relabelled as a blockchain success.
4. Enable checkpoint batching with a demo interval of one, then increase the
   event interval and add the time flush after measuring transaction cost and
   acceptable anchoring delay.
5. Mainnet promotion requires a dedicated RPC, external signer, nonzero gas cap,
   redundant reads, finality reconciliation and an approved incident owner.

### Safe rollback

1. If the chain or signer is unhealthy, first set
   `CREATORPROOF_PROOF_REQUIRE_CHAIN=false` so evidence processing can continue
   with an explicit degraded proof state.
2. Set `CREATORPROOF_PROOF_ANCHOR_MODE=merkle` to stop new direct transactions.
   Pause the checkpoint submitter but retain its ordered backlog.
3. Do not delete receipts, rewrite statements, revoke sound attestations, or
   rotate a key merely because of an application rollback. Historical proofs
   remain valid under their recorded deployment fingerprint.
4. Restore application/database code using the normal migration rollback only
   after taking a verified backup. Chain state itself is not rolled back.
5. Re-enable the sender from the oldest unanchored sequence. Reuse stored
   transaction hashes/idempotency keys so recovery cannot duplicate a batch.
6. Rotate and publish a new attester only for compromise or policy-driven key
   rotation. Record the old address and validity window permanently in the trust
   bundle.

Rollback never changes the evidence conclusion. It changes only whether a new
independent public timestamp can be produced.
