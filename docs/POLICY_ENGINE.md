# Policy-aware matching

CreatorProof's deterministic evaluator reads the copy result, source coverage, signed claim/license projections, versioned creator preferences, intended use, and the organization policy pinned at scan acceptance. It records these facts separately in `decision.policy_inputs` and the existing trace. A policy pass never erases the visual match, and a detector score never establishes infringement.

## Declare the intended use

Legacy multipart scan fields remain supported. New clients can optionally submit JSON in the multipart `use_context` field:

```json
{
  "territory": "US",
  "channel": "web",
  "audience": "public",
  "transformation": "resize",
  "platform": "approved-platform",
  "model": "declared-model-version",
  "rights_permission": "image_editing_permission"
}
```

`POST /v1/scans/from-upload` accepts the same object as `use_context`. The schema rejects unknown fields, invalid country-code shapes, control characters, and unsupported permission keys. Aliases such as `ai_training` normalize to the explicit passport field. Known intended-use labels can also select a permission.

These dimensions are caller declarations, not detected facts. `country_code` is separately stored as `submission_country_code` for case context and must not be interpreted as recipient residence or intended-use territory. The immutable input binding and idempotency digest include supplied context/country. Changing either with the same key returns 409; omitting both preserves legacy digest behavior.

## Evaluate recorded permissions

A License must have an authorizing state, valid effective dates, a listed intended use, no conflicting prohibited use, and matching restricted territory/channel/audience/transformation. Missing context for a restriction cannot authorize the use. Signed projection mismatches also fail closed. An active creator `ALLOW` preference is recorded preference evidence, not a newly manufactured contract.

Passport evaluation records relevant preference, effective/revocation/consent state, geographic scope, platform/model restrictions, attribution/licensing conditions, and missing facts. Expired, revoked, unknown, not-yet-effective, and unresolved conditional preferences route affected findings to review. These facts cannot mutate historical preference versions.

| Visual evidence and rights | Recorded result |
|---|---|
| Confirmed copy, applicable license, satisfied conditions | MATCH_FOUND + PASS_BY_POLICY |
| Confirmed copy, missing or mismatched license | MATCH_FOUND + REVIEW, or BLOCK if explicit organization rules require it |
| Partial reliable reuse, unresolved permissions | Match facts preserved + REVIEW |
| Style resemblance without correspondence | Advisory style signal, no copy accusation |
| Semantic neighbor or failed geometry | INCONCLUSIVE / NO_VALIDATED_COPY_REGION; human review where policy requires |
| Inadequate source coverage | Scoped evidence/abstention; no worldwide clearance |

The existing organization policy remains the decision authority. A rights denial does not become an automatic legal conclusion or notice. Assistant output cannot override this evaluator. Matrices preserve the final policy separately from evidence state and `legal_conclusion: null`.

## Validate

From `apps/api`, run `uv run pytest tests/test_phase1_policy_preferences.py tests/test_phase1_scan_context_retention.py tests/test_scan_flow.py`. Service cases check every permission and lifecycle/scope condition; actual API scans verify applicable US/web license passes and mismatched/missing scope reviews, without changing MATCH_FOUND. Other regression tests verify pinned organization policies, proof/trace binding, and existing review behavior.
