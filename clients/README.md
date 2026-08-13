# CreatorProof SDK quick starts

Two clients, one API. Both are dependency-free so integrating does not mean
adopting this project's dependency tree, and neither exposes anything the API
itself does not return.

Before you start, know what the API does and does not tell you:

- A result is **review evidence and a customer-policy decision**, never a legal
  finding of infringement.
- **Coverage comes before the decision.** A `PASS_BY_POLICY` over an
  `EMPTY_SCOPE` search means nothing was compared. Check
  `coverage_status == "COMPLETE"` before you treat a clean result as clean.
- A **local transparency receipt is not a blockchain.** Only
  a public `proof_kind` / receipt `anchor_scope` identifies an on-chain
  attestation. `commitment_scope` describes the bytes that were hashed, not
  where they were committed.

## Python

```bash
pip install ./creatorproof/clients/python
```

```python
from creatorproof import CreatorProofClient

client = CreatorProofClient("cpk_...", base_url="https://api.example.com")

work = client.register_work(
    "originals/harbour.jpg",
    title="Harbour study",
    catalog_id="studio-archive",
    rights_path="EXISTING_LICENSE",
    allowed_uses=["marketing/social"],
    claimant="Demo Creator",
)

scan = client.create_scan(
    "candidates/for-review.jpg",
    catalog_id="studio-archive",
    intended_use="marketing/social",
)
result = client.wait_for_scan(scan.id)

if not result.coverage_is_complete:
    raise SystemExit(f"Search was incomplete: {result.coverage_status}")

print(result.policy_action, result.match_status)
print("On a public chain:", result.proof.is_public_blockchain)

client.verification_package(result.id).save("package.json")
```

Then verify that package offline, with no network and no third-party packages:

```bash
python creatorproof/apps/api/scripts/verify_evidence_statement.py package.json
```

## TypeScript

```bash
cd creatorproof/clients/typescript && npm install && npm run build
```

```ts
import { CreatorProofClient, coverageIsComplete } from "@creatorproof/client";

const client = new CreatorProofClient(process.env.CREATORPROOF_API_KEY!, {
  baseUrl: "https://api.example.com",
  correlationId: crypto.randomUUID(),
});

const scan = await client.createScan({
  file: new Blob([bytes], { type: "image/jpeg" }),
  filename: "for-review.jpg",
  catalogId: "studio-archive",
  intendedUse: "marketing/social",
});

const result = await client.waitForScan(scan.id);
if (!coverageIsComplete(result)) {
  throw new Error(`Search was incomplete: ${result.evidence_packet?.scope?.coverage_status}`);
}
console.log(result.policy_action, result.match_status);
```

Keep the API key server-side. In a browser, call your own backend and let it
call CreatorProof, which is exactly what the demo console in `apps/web` does.

## Correlation IDs

Pass `correlation_id` (Python) or `correlationId` (TypeScript) and the same value
appears in API request logs, the scan's stage ledger, the signed statement, and
every webhook delivery for that scan. When a customer reports a problem, that one
identifier is enough to reconstruct what happened.

## Webhooks

See [WEBHOOKS.md](./WEBHOOKS.md) for the delivery format, signature scheme, retry
schedule and replay rules. Both clients ship a verification helper:
`verify_webhook_signature` in Python and `verifyWebhookSignature` in TypeScript.
