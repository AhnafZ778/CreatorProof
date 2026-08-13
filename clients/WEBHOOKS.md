# CreatorProof webhook specification

Version `v1`. Deliveries are signed, timestamped, retried and dead-lettered.
Everything below is implemented in `apps/api/app/services/webhooks.py`; if this
document and the code disagree, the code is the defect.

## Subscribing

```http
POST /v1/webhooks/endpoints
X-API-Key: cpk_...
Content-Type: application/json

{"url": "https://example.com/hooks/creatorproof", "event_types": ["scan.completed"]}
```

The response contains a `secret` **exactly once**. It is stored hashed and cannot
be recovered; if you lose it, create a new endpoint. An empty `event_types` array
subscribes to every event.

Endpoints resolving to private, loopback or link-local addresses are refused
unless `CREATORPROOF_WEBHOOK_ALLOW_PRIVATE_HOSTS=true`, which exists for local
development only.

## Request format

```http
POST /hooks/creatorproof
Content-Type: application/json
X-CreatorProof-Signature: v1=<hex hmac-sha256>
X-CreatorProof-Timestamp: 1786500000
X-CreatorProof-Delivery: whd_01J...
X-CreatorProof-Event: scan.completed
X-CreatorProof-Correlation-Id: 3f1c...
```

The body is compact JSON with sorted keys:

```json
{
  "delivery_id": "whd_01J...",
  "event_type": "scan.completed",
  "created_at": "2026-08-10T12:00:00+00:00",
  "data": { }
}
```

## Signature

The signed message is the timestamp, a literal `.`, then the exact raw request
body:

```text
signature = "v1=" + hex(HMAC_SHA256(secret, timestamp + "." + raw_body))
```

Verify against the **raw bytes** you received. Re-serializing the JSON changes
the bytes and the signature will not match.

Reject a delivery when the timestamp is more than 300 seconds from your clock.
Binding the timestamp into the signature is what makes a captured delivery
unusable later: an attacker cannot move it forward in time without invalidating
the signature.

`delivery_id` is stable across retries. Treat it as the idempotency key and
process each one once.

Both SDKs implement this: `verify_webhook_signature` (Python) and
`verifyWebhookSignature` (TypeScript).

## Events

| Event | Fired when | Key fields |
| --- | --- | --- |
| `scan.completed` | A scan reaches a terminal state with an evidence packet | `policy_action`, `match_status`, `coverage_status`, `coverage_complete`, `packet_hash_sha256`, `statement_id`, `review_case_id` |
| `review_case.opened` | A result requires human review | `review_case_id`, `scan_id`, `policy_action` |
| `statement.status_changed` | A correction, dispute, supersession or revocation is appended | `statement_id`, `statement_type`, `reason` |

Payloads carry summaries, not evidence. Fetch the authoritative packet over the
authenticated API using `scan_id`. Two fields deserve care:

- `coverage_complete` is `false` whenever the search did not cover the declared
  catalog. A `PASS_BY_POLICY` with `coverage_complete: false` has not cleared
  anything and must not be automated as an approval.
- `policy_action` is a decision under **your** policy. It is not a legal finding.

## Retries and dead letters

| Attempt | Delay before it |
| --- | --- |
| 1 | immediate |
| 2 | 2s |
| 3 | 4s |
| 4 | 8s |
| 5 | 16s |

Backoff is `min(600, 2^attempts)` seconds, capped at 10 minutes, for up to
`CREATORPROOF_WEBHOOK_MAX_ATTEMPTS` attempts (default 5). Any non-2xx response,
timeout or connection failure counts as a failure. After the final attempt the
delivery moves to `DEAD_LETTERED` and is never retried automatically.

Inspect deliveries, including dead letters and the last error, with:

```http
GET /v1/webhooks/deliveries?endpoint_id=whe_...
```

Return `2xx` quickly and do the work asynchronously. A slow endpoint produces
timeouts, which are indistinguishable from failures and consume your retries.

## Correlation

`X-CreatorProof-Correlation-Id` matches the correlation ID on the originating API
request, its scan record, its stage ledger and its signed statement. Log it and a
support question becomes a single lookup rather than an investigation.
