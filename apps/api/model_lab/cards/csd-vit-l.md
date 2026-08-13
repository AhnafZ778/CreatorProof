# Model card: CSD ViT-L experimental style descriptor

## Role

CSD supports catalog-relative creator-profile resemblance. It is not biometric
identity, authorship, ownership, proof of copying, proof of training-data use, or an
automatic block signal.

## Identity boundary

- Component: style-csd
- Provider: external CSD descriptor routed through CreatorProof
- Source repository and checkpoint repository: recorded by the fetch script
- Preprocessing: UPSTREAM_CSD_TRANSFORMS_BRANCH0
- Source commit: 3a9df32605b869eceb704897839be80977a9f1ea
- Checkpoint revision: 5bc26a6fb0487f3f00a2a7313135103a005b1b67
- Checkpoint SHA-256: 40e92fad63a361b8136100cd234c42d401ef9b34ff1748234318929ebcc7e7a1
- Current qualification: RUNTIME_READY and experimental

## Enrollment boundary

Only versioned profiles with CONFIRMED consent may authorize a learned-style review
escalation. Claimant-name grouping is explicitly marked as an unversioned prototype.
Revoked or unconfirmed enrollment remains descriptive and cannot escalate policy.

## Safety and fallback

Legacy pickle loading is disabled by default and requires both explicit opt-in and an
expected SHA-256. Any source/checkpoint/runtime failure falls back to transparent
diagnostic style features. Diagnostic fallback cannot attribute a creator.

## Known limits

Raw cosine and CSLS rank are not probabilities. Profiles need multiple representative
works, difficult same-tradition negatives, content-confound controls, and open-set
evaluation. The upstream weight discrepancy noted by the project blocks promotion
until the exact artifact is independently pinned and measured.
