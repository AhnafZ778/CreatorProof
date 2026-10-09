# Human Contribution Ledger

The ledger records factual steps in a registered work's creation and editing
history. It supports a creator's account of human and AI involvement without
calculating an ownership percentage or deciding whether a work is copyrightable.
Events are assertions supplied by an authorized caller, with links to supporting
asset records and evidence where available.

## Append an event

Use a tenant credential with `works:write`. The work must exist and be active.

```http
POST /v1/works/{work_id}/contributions
X-API-Key: <your CreatorProof credential>
Content-Type: application/json
```

```json
{
  "action_type": "AI_UPSCALE",
  "actor_type": "HUMAN",
  "actor_id": "artist-account-reference",
  "description": "Upscaled the artist's original sketch and selected an output.",
  "classification": "AI_ASSISTED_SUBSTANTIAL",
  "input_asset_ids": ["<registered input asset version ID>"],
  "output_asset_id": "<registered output asset version ID>",
  "software_or_model": "Editor version 1 / upscaler model",
  "model_provider": "local",
  "model_version": "version-1",
  "prompt_reference": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
  "human_decision": "Selected the second output and manually corrected edges.",
  "timestamp": "2026-10-09T00:00:00Z",
  "hash_before": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "hash_after": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "evidence_artifact_reference": "artifact:editing-session-1",
  "c2pa_reference": "manifest:editing-session-1"
}
```

Only `action_type` and a nonempty bounded `description` are required. Optional
fields are retained in the integrity projection rather than discarded. The server
assigns `event_id`, `work_id`, `sequence`, `created_by`, `created_at`,
`previous_event_hash`, and `event_hash`. A missing event timestamp defaults to the
current server time; supplying a historical timestamp does not change the recorded
creation time.

All input asset IDs must be registered in the same tenant. An output asset must
also belong to this work. IDs referring to missing or other-tenant assets return
`404`. Hashes must be 64 hexadecimal characters and are normalized to lowercase.
`hash_before`/`hash_after` are accepted aliases for `input_hash`/`output_hash`.
`event_type` is accepted as an input alias for `action_type`.

The prompt field accepts an opaque reference or SHA-256 identifier, with bounded
syntax; it is not a raw prompt field. Store any private prompt separately under
appropriate access controls. Evidence and C2PA references document what the caller
supplied; appending an event does not fetch those references, validate an external
manifest, or sign an asset.

## Supported actions and factual classifications

Action types are:

| Creation/capture | Editing/selection | Publication/source |
| --- | --- | --- |
| `ORIGINAL_CAPTURE` | `MANUAL_EDIT` | `EXPORT` |
| `ORIGINAL_SKETCH` | `AI_EDIT` | `PUBLICATION` |
| `AI_GENERATION` | `AI_UPSCALE` | `LICENSED_SOURCE_IMPORT` |
|  | `AI_BACKGROUND_REMOVAL` |  |
|  | `HUMAN_SELECTION` |  |
|  | `HUMAN_COMPOSITION` |  |
|  | `COLOR_CORRECTION` |  |
|  | `CROPPING` |  |

`actor_type` accepts `HUMAN`, `AI`, `SYSTEM`, or `UNKNOWN` and defaults to `UNKNOWN`.
The factual classification defaults to `UNKNOWN` and accepts:

- `HUMAN_CREATED`
- `AI_ASSISTED_SUBSTANTIAL`
- `AI_GENERATED_HUMAN_SELECTION`
- `AI_GENERATED_MINOR_MODIFICATION`
- `UNKNOWN`

These classifications describe the recorded process. They are not legal labels,
copyright registrations, infringement findings, or proof that the caller owns
the inputs.

## Read and verify

Both routes require `works:read` and the same tenant as the work:

```http
GET /v1/works/{work_id}/contributions
GET /v1/works/{work_id}/contributions/verify
```

The first route returns all events in sequence, a verification result, and
`copyrightability_determination: null`. This response is a JSON ledger export and
includes private authenticated factual fields; it is not the public verifier.
The second returns the chain verification result without the event descriptions.

Every event's canonical SHA-256 digest covers its event/work identifiers,
sequence, actor, action, description, classification, provider/model, input and
output hashes, prompt/source references, input and output asset IDs,
software/model, human decision, event timestamp, evidence/C2PA references,
previous hash, authenticated recorder and creation time. Verification checks
sequential numbering, each previous-hash link and every recomputed event digest.
A valid response includes `valid: true`, `event_count`, and `head_hash`. A damaged
chain reports `valid: false`, `broken_sequence`, and
`CONTRIBUTION_HASH_CHAIN_MISMATCH`.

Append operations lock the work where the database supports row locks and enforce
unique `(tenant_id, work_id, sequence)` ordering. A concurrent append conflict
returns `409`; retry after reading the latest head. The append transaction also
stores an audit event and signed integrity event. Transparency publication may
retry after a transient provider outage without losing the durable event.

## Corrections and limitations

Events are append-only. There is no update or delete endpoint. ORM guards and
database immutability triggers protect the supported databases; PostgreSQL also
applies tenant row-level security. If an earlier assertion is
wrong, append an appropriately described correction with the supporting
references. Do not edit the prior row. Deleting a work hides its history from
normal and public reads while preserving retained ledger records according to
the work's tombstone behavior.

Hash-chain verification detects changed event contents and broken links in the
available ledger. It does not independently establish that a recorded action
happened, prove ownership, or replace external audit/transparency evidence.
Claims about provenance should refer to the separate provenance inspection and
integrity APIs. The current API does not impose percentages of human contribution
or automatically decide copyrightability.

Public verification never includes contribution descriptions, raw prompts, actor
identity, source references, or private evidence. Use an expiring scoped
verification token for a safe registration/provenance/rights/packet summary; see
[AI_RIGHTS_PASSPORT.md](AI_RIGHTS_PASSPORT.md).

## Validation

```bash
cd apps/api
.venv/bin/pytest -q tests/test_phase1_passports.py
```

Tests append and verify a complete ledger, reject invalid asset references and
raw prompt input, verify every factual field participates in the hash, detect
tampered stored events, enforce append-only ORM behavior, and check tenant and
deleted-work boundaries.
