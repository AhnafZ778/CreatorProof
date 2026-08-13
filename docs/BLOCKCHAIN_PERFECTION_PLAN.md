# Blockchain perfection plan

Status: implementation plan and completion record, written 2026-08-12 against
`0.10.0`. Companion documents: `BLOCKCHAIN_IMPLEMENTATION_AND_DEPLOYMENT.md`
(operator runbook) and `BLOCKCHAIN_GOVERNANCE_AND_TRUST.md` (why a chain).

## 1. What was already right

The pre-existing anchoring layer is not the weak part of this project and is not
rewritten here:

- Real EAS attestation of a `bytes32` commitment on a public EVM network, with
  full attestation read-back rather than `isAttestationValid` alone.
- Durable anchor jobs, a cross-process signer lease, prepared-transaction
  persistence before broadcast, confirmation depth plus `safe`/`finalized`
  reconciliation.
- An RFC 6962 transparency tree with signed checkpoints, batched into one
  attestation per checkpoint root.
- Strict data minimization: only 32-byte commitments reach the chain.
- Honest labelling: a local Merkle receipt is never described as a blockchain.

## 2. The three real gaps

Measured against the BCOLBD blockchain criteria (Architecture & Governance 30,
Market & Partners 10, and the prototype's Governance 20 / Architecture 20), the
implementation had three structural gaps, not cosmetic ones.

| # | Gap | Consequence |
| --- | --- | --- |
| G1 | **One attester.** Only CreatorProof's key ever wrote to the chain. Counterparties could read a proof but could not bind themselves to it. | The network looked like a single vendor timestamping its own database. Membership governance had no on-chain expression. |
| G2 | **No membership or tokenized artifact.** Roles existed in documentation and in tenant credentials, never as an on-chain, independently readable structure. | Member on/off-boarding, permission structure and asset tokenization — all explicit scoring items — had no prototype evidence. |
| G3 | **Chain writes were configuration-dependent.** `auto` mode could resolve to a local Merkle receipt, and `proof_require_chain` did not force the rest of the deployment tuple to be pinned. | A misconfigured demo could silently fail the prototype's mandatory "back-end must write to a blockchain" criterion. |

## 3. What this change implements

### 3.1 Counterparty co-attestation (fixes G1)

A second, independent party binds itself to the same evidence commitment using
**its own EVM key**.

```text
CreatorProof                     Counterparty (brand / agency / creator)
     │                                        │
     │ 1. evidence packet -> packetHash       │
     │ 2. EAS attestation (platform key)      │
     │                UID ───────────────────►│
     │                                        │ 3. signs EIP-712 over bodyHash
     │◄──────── signed co-attestation ────────┤    with its own key
     │ 4. verify signature + membership       │
     │ 5. EAS attestation of coAttestationHash│
     │    with refUID = platform UID          │
```

Properties that matter to a reviewer:

- The counterparty's signature is verified against a **recovered EVM address**,
  not against a session cookie or an API key.
- Membership is checked against the on-chain registry when one is configured;
  an inactive or unknown member is refused.
- The EIP-712 domain pins `chainId` and `verifyingContract`, so a signature
  cannot be replayed onto another network or another deployment.
- The on-chain record binds to the platform attestation through `refUID`, so the
  two attestations are provably about the same evidence packet.
- The chain still receives only a 32-byte hash. The decision body, the party
  identity and any note stay off-chain.

Claim boundary, unchanged: a co-attestation proves *that this party committed to
this decision at this time*. It does not prove the decision was correct, that
the party had authority, or that any rights claim is true.

### 3.2 On-chain membership and a soulbound clearance receipt (fixes G2)

`blockchain-local/contracts/CreatorProofNetwork.sol` adds two contracts:

- **`CreatorProofMemberRegistry`** — governor-administered enrolment, suspension,
  reinstatement and off-boarding, each with an event. Roles are explicit
  (`PLATFORM`, `CREATOR`, `AGENCY`, `BRAND`, `MARKETPLACE`, `REVIEWER`,
  `REGULATOR_OBSERVER`). Governance transfer is two-step. A regulator observer
  address is recorded on-chain so oversight provisioning is visible rather than
  promised.
- **`CreatorProofClearanceReceipt`** — a deliberately non-transferable
  (ERC-5192-style `locked`) receipt token bound to a `packetHash` and an
  attestation UID. It is the tokenization answer that does not lie: the token
  represents *a completed pre-publication clearance check*, explicitly not
  ownership of the underlying work. The contract carries that sentence as a
  public constant so it cannot be quietly dropped from the pitch.

Minting stays an operator action through the deployment toolkit rather than a
second durable transaction pipeline inside the API. That is a deliberate scope
decision, recorded here so nobody presents it as more automated than it is.

### 3.3 Fail-closed competition profile (fixes G3)

- `proof_require_chain` now also requires a pinned chain id and a pinned
  attester address, in every environment rather than only in production.
- When counterparty attestation is enabled in an EAS deployment, its schema UID
  must be present; the capability reports `NOT_CONFIGURED` instead of silently
  doing nothing.
- `.env.competition.example` is a complete, copyable profile.
- `scripts/competition_preflight.py` fails closed on configuration *and* on live
  chain readiness, so "the demo writes to a blockchain" is a checked fact.

### 3.4 The signing surface in the browser

The prototype criterion asks for a UI, and a co-attestation is only meaningful if
the counterparty's key stays with the counterparty, so the signature has to
happen client-side. `CoAttestationPanel` sits under the existing proof panel on a
scan result and does exactly that: it asks the wallet for an account, fetches the
challenge, hands the typed data to `eth_signTypedData_v4`, and submits the
signature. The API key never leaves the Next server — the three routes under
`app/api/network/` proxy through the same helper as every other call.

The panel is built to be honest when the deployment is not ready. If the chain is
not configured it says the deployment is not accepting signatures and lists the
reasons rather than showing a button that fails; if signatures are accepted but
anchoring is not, it says so and warns that nothing on screen should be presented
as anchored. Each commitment renders its own binding checks, the attestation UID
and transaction hash, an explorer link where one is configured, and a standing
note that a commitment records who signed what and when, not that the decision
was right.

## 4. On-chain / off-chain boundary after this change

| Datum | Location |
| --- | --- |
| `bytes32` packet hash | On chain (platform attestation) |
| `bytes32` checkpoint root | On chain (batched lifecycle) |
| `bytes32` co-attestation body hash | **On chain (counterparty attestation, `refUID` → platform UID)** |
| Member address, role, status | **On chain (member registry)** |
| Clearance receipt token | **On chain (soulbound, references attestation UID)** |
| Decision body, party identity, notes | Off chain, signed, hashed into the commitment |
| Media, scores, embeddings, rights records | Off chain, never committed directly |

## 5. Deliberately not implemented

Recorded so the whitepaper and the Q&A stay consistent with the code:

- **No fungible token, no payment or royalty settlement.** No proven multi-party
  settlement requirement exists yet; adding one would be blockchain surface area
  for its own sake.
- **No on-chain policy execution.** Policy stays deterministic and off-chain; the
  chain commits the outcome.
- **No custom chain or consensus.** The deployment inherits Base (OP Stack)
  finality and the official EAS contracts; the local Ganache contracts are a
  development harness and are labelled as such.
- **No EAS delegated attestation yet.** The counterparty signs an EIP-712 payload
  that CreatorProof relays as its own attestation, with the signer address bound
  into the committed body. Migrating to native `attestByDelegation`, so the
  counterparty's address appears as the on-chain `attester`, is the documented
  next step.
- **KMS/HSM custody is still documented, not shipped.** The attester key remains
  an in-process environment secret; `custody_model` is reported honestly through
  the proof status surface rather than hidden.

## 6. Verification gates

A deployment may not call itself blockchain-enabled until all of these pass:

1. `scripts/competition_preflight.py` exits zero.
2. `scripts/blockchain_acceptance.py` confirms a live packet, checkpoint and
   counterparty anchor.
3. A counterparty co-attestation reaches `CONFIRMED` and its verification report
   shows: signature valid, member active, commitment matches, `refUID` binds to
   the platform attestation.
4. `GET /v1/proof/status` reports `chain_writes_enabled: true`.

### Executed on the local harness, 2026-08-12

Run against the Ganache deployment in `blockchain-local` (chain id `31337`), not
a public network, so it demonstrates the code path rather than public finality:

| Gate | Result |
| --- | --- |
| `competition_preflight` | `ready: true`, one warning: `FINALITY_POLICY_IS_CONFIRMATION_DEPTH_DEVELOPMENT_ONLY`, which is correct for a chain with no `safe` tag |
| `blockchain_acceptance` | `accepted: true`, live-reconciled `EVIDENCE_PACKET`, `TRANSPARENCY_CHECKPOINT` and `COUNTERPARTY_ATTESTATION` |
| Co-attestation read-back | All fourteen binding checks true, including `ref_uid_matches_expected` against the platform attestation UID |
| Membership | Counterparty enrolled through the registry contract; `memberStatus` returned `ACTIVE`/`BRAND` for the recovered signing address |

A public-testnet run must additionally set `eas_finality_policy` to `safe` or
`finalized`; the warning above is the gate that will catch a deployment that
forgets.

### The browser path, exercised over HTTP

The gates above drive the service layer. The demo, though, runs through a wallet
in a browser, so that path was run separately against the same Ganache
deployment: a counterparty key enrolled in the registry contract, a challenge
requested over HTTP, the EIP-712 payload signed by a key the API process never
holds, and the signature submitted back.

| Step | Result |
| --- | --- |
| `GET /v1/network/status` | `accepting_signatures: true`, `anchoring_ready: true`, registry readable with its governor and active member count |
| `POST /v1/network/co-attestations/challenge` | `200`, typed data carrying `EIP712Domain`, `chainId` and the registry as `verifyingContract` |
| Wallet signature | Recovered to the signing address, confirming the payload the browser hands `eth_signTypedData_v4` verifies unchanged server-side |
| `POST /v1/network/co-attestations` | `201`, state `ANCHOR_PENDING` |
| Dispatcher | Job reached `CONFIRMED` with an attestation UID and transaction hash |
| Read-back | All six view checks true, including `on_chain_ref_uid_matches_platform_attestation` |

The refusals were exercised on the same live deployment, since a gate that has
never been seen to fail is not evidence of anything:

| Attempt | Response |
| --- | --- |
| Un-enrolled key requests a challenge | `403 MEMBER_NOT_ACTIVE`, decided by the registry contract rather than the local table |
| Body edited after signing | `422 SIGNER_ADDRESS_MISMATCH` |
| Body signed by a different key than it names | `422 SIGNER_ADDRESS_MISMATCH` |

### Correction found while running the gates

`scripts/blockchain_acceptance.py` compared the statement signer's `key_source`
with `CONFIGURED_PRIVATE_KEY`, a value the signer never emits, so gate 2 could
not pass on any deployment. It now compares with `CONFIGURED`, which is the
signer's own vocabulary for an operator-supplied key.
