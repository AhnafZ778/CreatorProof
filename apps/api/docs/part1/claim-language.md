# CreatorProof claim-language contract

## Allowed short claims

- Searches the declared registered catalog.
- Finds exact matches and can support transformed or partial-reuse review when robust
  geometry and aligned structure corroborate the candidate.
- Checks Content Credentials when the configured runtime is available.
- Reports visible AI labels as forgeable observations.
- Reports passive AI-origin evidence with calibration and availability limits.
- Compares an image with consent-backed creator profiles as advisory resemblance.
- Applies the selected declared-rights policy and records a deterministic trace.
- Commits to the Evidence Packet; the packet states whether that commitment is local
  or anchored by a mined public-chain transaction.

## Prohibited or unsupported claims

- Proves infringement, plagiarism, theft, ownership, authorship, or copyright safety.
- Searches the whole internet or clears all possible sources.
- Proves an image is human-made because provenance or detector evidence is absent.
- Identifies a generator universally.
- Proves a model trained on a creator's work.
- Identifies a creator from style or treats style resemblance as copying.
- Makes a local Merkle receipt sound like blockchain.
- Calls a source-verified, smoke-tested, or undersized result accurate, calibrated,
  compliant, production-ready, or commercially approved.

## Required vocabulary

| Internal fact | Safe customer wording |
| --- | --- |
| MATCH_FOUND | Supported match in the checked catalog |
| NO_MATCH_IN_CHECKED_SOURCES | No supported match in the declared checked sources |
| SCOPE_INCOMPLETE | Check incomplete; review required |
| VALID_TRUSTED C2PA AI assertion | Trusted signed source information identifies AI use |
| NOT_PRESENT C2PA | No Content Credential found; origin remains unresolved |
| Passive detector score | AI-origin signal, not an authorship probability |
| Visible marker | Visible, forgeable AI-label observation |
| Style profile result | Creator-profile resemblance, not attribution or copying |
| PASS_BY_POLICY | Allowed by the selected declared policy, not legal clearance |
| Local Merkle receipt | Local tamper-evident transparency receipt |
| Mined EAS receipt | Public-chain commitment receipt |

## Score semantics

Copy evidence index, detector raw scores, style cosine, CSLS, catalog percentile, and
diagnostic factor similarities are not probabilities unless a packet explicitly names
a compatible held-out calibration. Even calibrated origin output applies only to the
recorded provider, artifact bytes, preprocessing, crop policy, domain, and support
counts.

## Independence rules

- Style cannot create MATCH_FOUND.
- Origin cannot create or erase copy evidence.
- Proof cannot improve evidence or rights.
- Rights change routing, not visual evidence.
- Retrieval rank cannot substitute for verification.
- Missing capability cannot become negative evidence.
- A claimant label cannot substitute for corroborated rights or profile consent.

Every UI string, pitch slide, report caption, and judge answer should pass this
contract.
