# Blockchain governance, identity, privacy, and multi-party trust

This document answers the central question for the blockchain category: **why
does this problem need a chain rather than a well-run database?** Deployment and
acceptance procedures live in `BLOCKCHAIN_IMPLEMENTATION_AND_DEPLOYMENT.md`.

## 1. Why a chain is necessary here

A single service can store a hash. It cannot credibly attest to *when* it stored
it, because the same service controls the clock, the storage and the audit log.

CreatorProof's evidence is used in disputes between parties who do not trust each
other and, critically, do not trust CreatorProof either:

| Party | What they need | Why our word is not enough |
| --- | --- | --- |
| Creator | Prove their work was registered before a disputed publication | We are the counterparty's vendor |
| Brand / publisher | Prove a pre-publication check happened before release | Self-reported timestamps are worthless in a dispute |
| Agency / marketplace | Reconcile two customers' conflicting claims | Each side distrusts the other's records |
| Reviewer / auditor | Verify a decision months later, after staff turnover | Internal logs can be edited |
| Regulator or court-appointed expert | Verify without our cooperation | We might be uncooperative, acquired, or gone |

A public attestation gives every one of them the same fact, verifiable without us.
That is the multi-party trust problem; hash storage is merely the mechanism.

**The honest limit.** The chain proves *this exact evidence packet existed at this
time and was attested by this key*. It proves nothing about whether the evidence
is correct, whether the claim is true, or whether any use is lawful. Anyone who
states otherwise in a demo is misrepresenting the system.

## 2. Two-layer trust architecture

```text
Layer 1 — Local transparency log (always on, no chain required)
  Evidence Statement v2 -> JCS canonicalization -> Ed25519 / COSE_Sign1
    -> Merkle leaf -> signed checkpoint
  Guarantees: authenticity, integrity, append-only history, offline verification
  Does NOT guarantee: independent time, resistance to a fully compromised operator

Layer 2 — Public EVM attestation via EAS (required in a blockchain deployment)
  direct: bytes32 packetHash -> EAS attestation -> confirmed transaction -> UID
  batch:  signed domain-event leaves -> Merkle checkpoint -> bytes32 checkpointHash
  multi:  counterparty EIP-712 signature -> bytes32 coAttestationHash, refUID -> packet UID
  Guarantees: independent public ordering/time, shared record, third-party verifiability
  Does NOT guarantee: correctness of anything the hash commits to
```

Layer 1 is real cryptography and is never described as a blockchain. Layer 2 is
the blockchain. Proof responses keep them apart through an explicit anchor scope:

| Anchor scope | Meaning |
| --- | --- |
| `PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY` | Packet hash confirmed on a public EVM chain |
| `PUBLIC_EVM_ATTESTATION_CHECKPOINT_HASH_ONLY` | Signed Merkle-checkpoint hash confirmed on a public EVM chain |
| `PUBLIC_EVM_ATTESTATION_COUNTERPARTY_HASH_ONLY` | Counterparty commitment hash confirmed on a public EVM chain |
| `LOCAL_APPEND_ONLY_LOG_NOT_BLOCKCHAIN` | Transparency receipt only |

### Why the third lane exists

The first two lanes are both signed by CreatorProof's key, so a sceptic can
reasonably say the chain only proves that one vendor said something at a
particular time. A co-attestation is signed by a **different party's** key, and
CreatorProof cannot produce it. Only the digest of the counterparty's canonical
decision body is published, and `refUID` binds it to the packet attestation, so
the two records are provably about the same evidence.

What a co-attestation proves: this member committed to this decision, about this
packet, at this time. What it does not prove: that the decision is correct, that
the member held authority to make it, or that any rights claim is true.

## 3. On-chain / off-chain boundary

Nothing that identifies a person, a work, or a customer ever reaches the chain.

| Data | Location | Reason |
| --- | --- | --- |
| `bytes32` canonical packet hash | **On chain for direct scan proof** | Immediate existence/time proof for the demo and high-value tier |
| `bytes32` signed checkpoint hash | **On chain for batched lifecycle proof** | Covers registrations and rights/status events efficiently |
| `bytes32` counterparty body hash | **On chain for multi-party proof** | Binds a second party to a decision without publishing the decision |
| Member address, role code, status code | **On chain (member registry)** | A reviewer must be able to check membership without asking us |
| Clearance receipt token | **On chain, non-transferable** | Represents a completed check; deliberately not ownership, and deliberately not tradable |
| Attester address, schema UID | **On chain** | Required for verification |
| Member display name, organization, decision note | Off chain | Commercial relationships are not public data |
| Evidence packet, scores, matched regions | Off chain (database) | Commercially sensitive, and large |
| Images and derived artifacts | Off chain (object storage) | Personal data; must remain deletable |
| Tenant, creator, claimant identity | Off chain | Privacy, and the GDPR right to erasure |
| Rights claims and licences | Off chain | Mutable state; the chain must not carry it |
| Statement signatures and Merkle tree | Off chain (transparency log) | Full auditability without publishing content |

On-chain data minimization: **one 32-byte commitment per direct packet or batch
checkpoint.** Because the input includes high-entropy identifiers and is hashed
with SHA-256, the on-chain record is not a content-retrieval mechanism. Deleting
off-chain data removes the content while intentionally leaving an irreversible
commitment. Low-entropy fields must never be hashed and published alone because
dictionary attacks remain possible.

## 4. Roles and permissions

| Role | May issue claims | May corroborate | May dispute | May revoke | May co-attest | May attest on chain | May verify |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Creator | Own works | No | Own claims | Own claims | Yes, as a member | No | Yes |
| Agency (delegated) | On behalf of a represented creator | No | Represented claims | Represented claims | Yes, as a member | No | Yes |
| Brand / publisher | No | No | Claims affecting them | No | Yes, as a member | No | Yes |
| Marketplace | No | Marketplace-verified only | Listed items | Listed items | Yes, as a member | No | Yes |
| Reviewer | No | Yes, within their tenant | Yes | No | Yes, as a member | No | Yes |
| Regulator observer | No | No | No | No | No | No | Yes, plus a recorded on-chain address |
| Platform attester | No | No | No | No | No | **Yes** | Yes |
| External verifier | No | No | No | No | No | No | Yes |

Three separations are deliberate:

1. **The attester is not a claimant.** The platform key attests only that a packet
   existed. It never asserts that a rights claim is true. Merging these would
   turn a timestamp into an ownership registry it cannot support.
2. **Corroboration is not self-service.** `ASSERTED` is what a user typed;
   `CORROBORATED` requires a reviewer. Only a corroborated claim can authorize a
   recorded use, enforced in `app/services/policy_store.py`, not in the UI.
3. **Co-attesting is not attesting.** A member commits to its own decision with
   its own key. It never signs the platform's statement about the evidence, and
   the platform never signs the member's decision.

### Network membership

Onboarding: an organization is issued a tenant, an `ORG_ADMIN` principal, and
scoped API credentials. A counterparty that will co-attest is additionally
enrolled in `CreatorProofMemberRegistry` by the governor, with an explicit role
and an `ACTIVE` status; `PUT /v1/network/members` only records the identity
metadata that must stay off chain. Reviewer principals are created by the org
admin.

Offboarding: credentials are revoked, the registry entry is suspended or
offboarded (both emit events), data is deleted with a deletion receipt, and
prior attestations remain on chain by design — a public timestamp cannot be
withdrawn, which is precisely why it is trustworthy. Statement status is used to
mark records superseded or revoked instead.

Registry governance is two-step: the sitting governor proposes a transfer and
the successor must call `acceptGovernance`, so a mistyped address cannot lock
the registry. A regulator-observer address is recorded on chain so oversight
provisioning is visible rather than promised.

An unreadable registry is treated as an unknown answer, and an unknown answer is
not permission: with `CREATORPROOF_COUNTERPARTY_MEMBERSHIP_REQUIRED=true` a
registry outage refuses new co-attestations instead of quietly falling back to
the local member table.

## 5. Governance

### Business governance

- Policy versions are immutable and versioned. A decision permanently records the
  policy version it was made under, so a later policy change never rewrites history.
- Disputes append a `DISPUTE` statement; the original statement stays byte-identical
  and verifiable. Resolution appends `CORRECTION` or `SUPERSESSION`.
- Revocation is an append, never a delete. A verifier that checks only the
  signature and not the status will see a valid signature on a superseded record,
  which is why every verifier in this repository reports status alongside validity.

### Technology governance

- **RPC dependency.** A single RPC provider is a single point of failure. Failures
  are typed and retried with backoff; a scan never fails because anchoring failed.
  The receipt records `PENDING` or `FAILED` honestly and the evidence stands on
  Layer 1.
- **Chain-required deployment.** Set `CREATORPROOF_PROOF_ANCHOR_MODE=eas` and
  `CREATORPROOF_PROOF_REQUIRE_CHAIN=true`. `chain_required` is not a valid mode.
  Strict readiness/export gates must fail instead of silently presenting a local
  receipt as blockchain proof.
- **Confirmations and finality.** `eas_required_confirmations` is a block-depth
  gate. Production also stores the receipt block hash and reconciles canonical,
  safe and finalized inclusion; counting blocks alone is not reorg protection.
- **Efficient lifecycle coverage.** Work registrations and rights/status changes
  enter the signed transparency tree and are anchored through checkpoint batches.
  Direct per-packet EAS writes remain for the competition demo and high-value cases.
- **Signer rotation.** See the key-management runbook below.

## 6. Key management

Two independent key classes. Compromising one does not compromise the other.

| | Statement signing key | Chain attester key |
| --- | --- | --- |
| Algorithm | Ed25519 | secp256k1 (EVM) |
| Holds value | No | Yes (gas) |
| Storage | `CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX`, from a secret manager | Testnet: injected secret; production target: KMS/HSM/managed relayer |
| Exposure | Never logged; never in a trust bundle | Never exposed to the API/browser/verifier; current in-process key is transitional |
| Rotation | New `kid`, old public key retained in the trust bundle | New attester address, recorded in receipts |
| Blast radius | Forged statements from rotation time forward | Spurious attestations and gas loss |

### Rotation runbook (planned)

1. Generate a new key in the secret manager. Never on a laptop, never in a repo.
2. Register the new `kid` with `register_signing_key`; both keys are now published.
3. Set the new key as active. New statements use it; old ones still verify against
   the retained public key.
4. Mark the old key inactive after the overlap window. Do **not** delete it: every
   historical statement depends on it for verification.
5. Record the rotation in the audit log and publish the updated trust bundle.

### Compromise runbook (emergency)

1. **Contain.** Revoke the credential and disable the signer:
   `CREATORPROOF_STATEMENT_SIGNING_ENABLED=false`. The API keeps working and marks
   statements unsigned — visibly degraded rather than falsely trusted.
2. **Assess.** Use the transparency log to establish the tree size at the last
   known-good checkpoint. Any leaf after that point is suspect. Run
   `GET /v1/proof/transparency/consistency` to detect equivocation.
3. **Publish.** Mark the compromised `kid` inactive with a compromise timestamp.
   Verifiers must treat signatures after that time as untrusted.
4. **Rotate.** Follow the rotation runbook.
5. **Re-attest.** Re-sign affected statements with the new key as `CORRECTION`
   statements referencing the originals. Never rewrite the originals.
6. **Notify.** Every affected tenant, with the affected time window and the list of
   statement IDs. Silence here is the actual failure.

For the chain key, add: rotate to a new attester address, publish it, and treat
attestations from the compromised address after the compromise window as
untrusted. On-chain history cannot be erased, so disclosure is the only remedy.

## 7. Privacy threat model

| Threat | Mitigation | Verified by |
| --- | --- | --- |
| Cross-tenant data access | Tenant binding on every request plus PostgreSQL RLS with `FORCE` | `migrations/versions/0003_row_level_security.py`, tenancy tests |
| Stolen API key | Keys stored as HMAC-SHA256 digests with a pepper; scoped; revocable; every use audited | `test_platform_api.py` credential tests |
| Privilege escalation via scope | A credential can narrow but never widen its role's scopes | `_parse_scopes` in `core/security.py` |
| Personal data on a public chain | Only a `bytes32` hash is published; the member registry publishes an address, a role code and a status code, never a name | On-chain/off-chain table above |
| Replaying a counterparty signature onto another deployment | The EIP-712 domain pins `chainId` and the registry contract; the body pins the deployment id, scan and packet hash | `test_body_shaped_for_another_deployment_is_refused` |
| Presenting a co-attestation against a different packet | The submitted body must reference the scan's platform attestation UID, and `refUID` is verified on read-back | `test_body_that_omits_the_platform_attestation_is_refused`, `test_coattestation_pointing_at_another_packet_attestation_is_rejected` |
| A leaked signature submitted later by someone else | Bounded acceptance window plus a per-body nonce and a uniqueness constraint on the body hash | `test_stale_signature_is_refused`, `test_replayed_submission_does_not_create_a_second_commitment` |
| Right to erasure vs. immutable chain | Content is off chain and deletable; the on-chain hash commits to data nobody can reconstruct | Deletion receipt tests |
| Incomplete deletion | Receipts list retained objects explicitly | `delete_work` returns `objects_retained` |
| Operator tampering with history | Append-only triggers, Merkle log, signed checkpoints, offline verification | Migration 0003, transparency tests |
| Log leakage of secrets | Structured logs carry identifiers, never key material or image bytes | `observability.py` |
| Webhook replay | Timestamp bound into the signature, 300-second window, stable delivery IDs | `test_webhook_signature_verifies_and_rejects_a_replay` |
| SSRF through webhook URLs | Private, loopback and link-local destinations blocked by default | `_is_private_host` |

## 8. Dispute, revocation and supersession flow

```text
Statement issued (ACTIVE)
  ├── contested        -> DISPUTE      -> status DISPUTED,   original intact
  ├── evidence changed -> CORRECTION   -> status CORRECTED,  original intact
  ├── rescanned        -> SUPERSESSION -> status SUPERSEDED, original intact
  └── withdrawn        -> REVOCATION   -> status REVOKED,    original intact
```

Every transition is a new signed statement in the transparency log. Verification
of the original still succeeds — and must, or the log would be rewritable. This is
why every verifier reports the current status next to the signature result: a
cryptographically valid statement can still be one that has been superseded.

## 9. Partner incentives

| Partner | Gets | Gives |
| --- | --- | --- |
| Creator | Timestamped registration and dispute evidence they can use anywhere | Reference works for the catalog |
| Brand / publisher | Documented pre-publication diligence | Scan volume and policy configuration |
| Agency | One reconciled rights position across represented creators | Claim and licence records |
| Marketplace | Corroboration authority that raises listing trust | Verification of seller identity |
| Insurer / legal | Independently verifiable evidence trail | Underwriting or advisory demand |

The shared layer is worth more to each party than a private log, because a private
log is only as good as its owner's reputation with the other side of a dispute.

## 10. Metrics

| Metric | Where it comes from |
| --- | --- |
| Independent roles and attesters | Principal roles in use per tenant |
| Revocation propagation time | Status statement timestamp minus request timestamp |
| Key rotation recovery time | Rotation drill, measured end to end |
| Unauthorized access test results | Scope and tenant isolation tests, all passing |
| On-chain data minimization | 32 bytes per direct packet, batch checkpoint or counterparty commitment |
| Independent attesting parties | Active members in the on-chain registry, and distinct signing addresses on confirmed co-attestations |
| Independent verifier success rate | Offline verifier over sampled packages |
