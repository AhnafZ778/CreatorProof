# Operations runbook

Sprints S13, S14 and S17. Written to be usable at 3 a.m. by someone who did not
build the system.

## 1. Health, readiness and metrics

| Endpoint | Use it for | Key rule |
| --- | --- | --- |
| `GET /healthz` | Liveness | Says the process is up, nothing more |
| `GET /readyz` | Traffic gating | Lists `degraded_capabilities` explicitly |
| `GET /metrics` | Prometheus scrape | In-process counters and gauges |

Readiness never hides a degraded dependency to keep a green light. If the signer
is disabled or the queue is unreachable, it says so and the UI shows a banner.
A green check over a broken detector is the failure this product cannot afford.

### Metrics worth alerting on

| Metric | Alert when | Means |
| --- | --- | --- |
| `creatorproof_outbox_failed_total` | Any increase | Accepted scans are not reaching workers |
| `creatorproof_stage_lease_reclaimed_total` | Sustained increase | Workers are dying mid-stage |
| `creatorproof_webhook_dead_lettered_total` | Any increase | A customer is silently missing events |
| `creatorproof_scan_failed_total` by `error_code` | Rate change | A provider or model regressed |
| Outbox pending count | Growing for 5+ minutes | Dispatcher stalled or queue down |

## 2. Correlation IDs

Every request gets an `X-Correlation-Id` (accepted from the caller or generated).
It flows into request logs, the scan row, the stage ledger, the signed statement
and every webhook delivery. Given one ID, the whole path is:

```bash
rg '"correlation_id":"<id>"' /var/log/creatorproof/*.log
```

Start every investigation by getting this ID from the customer. It converts a
vague report into a single lookup.

## 3. Common incidents

### Scans accepted but never processed

1. `GET /readyz` — check `queue` and `outbox`.
2. Outbox pending count high and rising: the dispatcher or Redis is down. Restart
   the worker; the outbox replays automatically because nothing was ever lost.
3. Outbox drained but no stage rows: no worker is consuming. Check the consumer
   group with `XINFO GROUPS creatorproof:scan.accepted`.
4. Stages `RUNNING` with expired leases: the reaper reclaims them within
   `stage_lease_seconds`. Confirm with `creatorproof_stage_lease_reclaimed_total`.

**Do not** re-submit the scan for the customer. Idempotency binds a request digest
to a scan; a re-submission with the same key returns the original scan, and with a
different key produces a second scan that will confuse the audit trail.

### Anchoring is stuck on PENDING

1. `GET /v1/proof/status` for provider, chain and configuration.
2. `GET /v1/proof/preflight` to test every RPC, chain ID, EAS bytecode/schema,
   pinned attester and signer balance. A connected RPC is not sufficient.
3. If a transaction hash exists, inspect it before retrying. A timeout after
   broadcast may still mine; creating a replacement blindly can duplicate proof.
4. If the attester balance is below the configured runway, fund only the dedicated
   signer address and confirm the chain before sending funds.
5. If the chain is down: evidence is unaffected. Statements are still signed and
   logged locally. Say exactly this to the customer — the evidence stands on the
   transparency log; only the independent timestamp is delayed.
6. For domain-event batches, inspect oldest unanchored sequence, lease owner,
   attempt count and next retry. Expire an abandoned lease; never delete/reorder
   the backlog or create a second checkpoint for the same tree size.
7. Never present a local receipt as a chain attestation to close a ticket.

The full activation, acceptance and rollback procedure is in
`BLOCKCHAIN_IMPLEMENTATION_AND_DEPLOYMENT.md`.

### Webhook deliveries are dead-lettering

1. `GET /v1/webhooks/deliveries?endpoint_id=...` and read `last_error`.
2. `WEBHOOK_PRIVATE_HOST_BLOCKED`: the customer pointed at a private address.
3. Repeated timeouts: the endpoint is too slow. It must return 2xx quickly and do
   the work asynchronously.
4. Signature mismatches on the customer side: they are almost certainly
   re-serializing the JSON before verifying. Point them at the raw-bytes rule in
   `clients/WEBHOOKS.md`.

### A tenant reports seeing another tenant's data

Treat as a Sev-1 immediately.

1. Capture the correlation ID and freeze the evidence; do not restart anything.
2. Confirm PostgreSQL and that migration `0003_row_level_security` is applied:
   `SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='works';`
   Both must be true.
3. Confirm `CREATORPROOF_ENABLE_POSTGRES_RLS=true` and that no session is running
   with `app.bypass_rls`.
4. Audit the scope: query `audit_events` for the affected window.
5. Notify affected tenants. Under most regimes this is a reportable event and the
   clock starts at discovery, not at diagnosis.

## 4. Drills

Run these before any pilot. A runbook that has never been executed is fiction.

### Recovery drill

1. Submit ten scans.
2. `kill -9` the worker mid-run.
3. Restart it. Expect: leases reaped, stages resumed, ten completed scans, no
   duplicate evidence packets, no lost work.

### Deletion drill

1. Register a work, scan against it, then `DELETE /v1/works/{id}`.
2. Check the receipt: `objects_retained` must be empty.
3. Confirm the bytes are gone from object storage.
4. Confirm the on-chain hash remains and that this is expected: it commits to data
   that no longer exists and cannot be reconstructed.

### Key rotation drill

Follow the rotation runbook in `BLOCKCHAIN_GOVERNANCE_AND_TRUST.md`. Success is
new statements verifying under the new key **and** old statements still verifying
under the retained public key. Separately rotate the EVM attester, publish the
new deployment fingerprint, and prove that historical attestations remain bound
to the old address and its validity window. Measure the elapsed time; that is your
recovery time.

### Rollback drill

1. `python scripts/migrate.py backup`
2. `python scripts/migrate.py downgrade --revision <previous>`
3. Verify the API starts and serves reads.
4. `python scripts/migrate.py upgrade`

For a blockchain-sender rollback, first disable strict chain requirement, select
the explicitly local `merkle` provider, and pause dispatch while retaining its
ordered backlog. Never attempt to roll back public chain state or delete historical
receipts. Follow section 10 of `BLOCKCHAIN_IMPLEMENTATION_AND_DEPLOYMENT.md`.

Migrations refuse to downgrade without a verified backup, and for PostgreSQL the
tool prints the exact `pg_dump` command rather than pretending it took one.

## 5. Configuration traps

| Setting | Trap |
| --- | --- |
| `CREATORPROOF_DEV_API_KEY` | A default or weak key is refused in production |
| `CREATORPROOF_DEV_AUTH_ENABLED` | Must be false in production; it bypasses stored credentials |
| `CREATORPROOF_API_KEY_PEPPER` | Changing it invalidates every stored credential |
| `CREATORPROOF_STATEMENT_SIGNING_PRIVATE_KEY_HEX` | Empty in production means unsigned statements; startup refuses this |
| `CREATORPROOF_TRUSTED_ISSUER_KEY_SHA256` | Must be pinned through an independent channel; a key shipped inside its own package is not trusted |
| `CREATORPROOF_ENABLE_POSTGRES_RLS` | False disables the database-level tenant guarantee |
| `CREATORPROOF_PROOF_ANCHOR_MODE` | `auto` falls back to a local receipt; `eas` pins to the chain |
| `CREATORPROOF_PROOF_REQUIRE_CHAIN` | True fails loudly instead of downgrading to a local receipt |
| `CREATORPROOF_EAS_RPC_URLS_JSON` | Keep ordered redundant RPCs; credential-bearing URLs are secrets |
| `CREATORPROOF_EAS_CHAIN_ID` | Must match RPC and the deployment trust manifest |
| `CREATORPROOF_EAS_CONTRACT_ADDRESS` | Pin the official contract and its runtime-code digest |
| `CREATORPROOF_EAS_SCHEMA_UID` | Must resolve to exactly the configured schema definition |
| `CREATORPROOF_EAS_REQUIRED_ATTESTER_ADDRESS` | Must equal the independently derived signer address |
| `CREATORPROOF_EAS_REQUIRED_CONFIRMATIONS` | Block depth is not economic finality; reconcile block hash and safe/finalized state |
| `CREATORPROOF_EAS_MAX_FEE_PER_GAS_GWEI` | Zero disables the cost circuit breaker; do not use zero on mainnet |
| `CREATORPROOF_BLOCKCHAIN_DOMAIN_ANCHORING_ENABLED` | Disable only to stop new batch sends; retain ordered pending records |
| `CREATORPROOF_WEBHOOK_ALLOW_PRIVATE_HOSTS` | Development only; an SSRF vector in production |
| `CREATORPROOF_JOB_BACKEND` | `inline` blocks the request thread; never in production |

## 6. Usage metering and quotas

`usage_records` meters scans, protected assets, storage bytes, GPU stage seconds,
proof anchors and retention tier. Daily scan quotas are enforced at accept time in
`scans.py`, which returns 429 with the limit and used count rather than queuing
work a customer cannot use.

`GET /v1/usage?window_days=30` returns the aggregate for the calling tenant only.
Two properties matter operationally:

- Meters with no activity report zero rather than being omitted. A dashboard must
  never read "not measured" as "nothing used".
- The endpoint returns quantities, never prices. Rates come from a rate card
  measured against a shadow run, not from a hard-coded field.

Metering never fails a request. A meter that cannot be written is logged as
`usage_record_persist_failed` and swallowed, on the same reasoning as the audit
trail: losing a billing row is bad, but turning a successful scan into a 500 over
a counter is worse. If that warning appears, reconcile from `audit_events`, which
records the same operations independently.

`creatorproof_usage_recorded_total` is labelled by meter and is the cheapest way
to confirm metering is live without querying the database.

### Cost model per scan (measure, do not guess)

| Component | Driver | Notes |
| --- | --- | --- |
| CPU | Fingerprints, geometry, canonicalization | Dominant when no GPU model runs |
| GPU | Learned retrieval and origin models | Zero in baseline mode |
| Storage | Candidate retention plus derived artifacts | Controlled by `candidate_retention_seconds` |
| Queue | Redis Streams entries | Negligible |
| Proof | Gas per attestation | Only when anchoring; batch checkpoints reduce it |
| Support | Reviewer minutes per review case | Usually the largest real cost |

Publish support promises only against measured numbers from a shadow run.

### Building the rate card

1. Run a representative workload with `CREATORPROOF_TENANT_SCAN_QUOTA_PER_DAY=0`.
2. Read `GET /v1/usage` for the metered quantities.
3. Divide measured infrastructure spend for the window by those quantities.
4. Re-measure whenever a model is promoted; GPU seconds move the most.

`gpu_stage_seconds` is zero on a CPU-only deployment. That is a real measurement,
not a gap: the baseline configuration runs no GPU model, and pricing a pilot as
though it did would overstate cost.
