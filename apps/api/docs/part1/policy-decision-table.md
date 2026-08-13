# CreatorProof demo policy decision table

- Policy version: creatorproof-demo-policy-v1
- Output vocabulary: PASS_BY_POLICY, REVIEW, BLOCK
- Current implementation uses PASS_BY_POLICY and REVIEW; BLOCK is reserved for a
  future explicitly configured customer rule.

Rules are evaluated in this safety order:

| Priority | Condition | Action | Core reason |
| --- | --- | --- | --- |
| 1 | Scope incomplete | REVIEW | SCOPE_INCOMPLETE_REQUIRES_REVIEW |
| 2 | Scan error or visual evidence inconclusive | REVIEW | SCAN_ERROR_REQUIRES_REVIEW or VISUAL_EVIDENCE_INCONCLUSIVE |
| 3 | Complete declared-catalog no-match | PASS_BY_POLICY | NO_MATCH_IN_DECLARED_CATALOG plus clearance boundary |
| 4 | Positive match with incomplete coverage | REVIEW | MATCH_FOUND_WITH_INCOMPLETE_SCOPE_REQUIRES_REVIEW |
| 5 | Match without a valid rights record | REVIEW | Missing/invalid rights reason |
| 6 | Rights path disputed | REVIEW | MATCHED_RIGHTS_RECORD_DISPUTED |
| 7 | Claim not corroborated | REVIEW | Claim-state-specific reason |
| 8 | Corroborated existing license includes exact intended use | PASS_BY_POLICY | MATCHED_USE_ALLOWED_BY_RIGHTS_RECORD |
| 9 | License may be available | REVIEW | LICENSE_PATH_AVAILABLE_REVIEW_REQUIRED |
| 10 | Any other matched case | REVIEW | MATCH_REQUIRES_RIGHTS_REVIEW |

## Overlay rules

Creator-profile resemblance never creates a copy match or block. Under the default
INFORMATIONAL origin mode, origin/style facts are recorded but do not turn a policy
pass into review. Under REQUIRED mode, a configured origin result may route a
PASS_BY_POLICY to REVIEW. That route is explicitly not an infringement finding.

Profile review escalation is first suppressed when enrollment consent is not
CONFIRMED. Proof status has no policy effect.

## Replay

Every packet records policy inputs, outputs, matched reason codes, missing facts,
policy version, and a deterministic SHA-256 trace digest. A later policy version must
produce a new evaluation or dry run and cannot mutate the old trace.
