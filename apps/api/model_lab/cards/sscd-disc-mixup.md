# Model card: SSCD DISC Mixup

## Role

SSCD nominates visually related registered works for pairwise copy verification. It
does not decide copying, infringement, ownership, or permission. A non-identical
match still requires robust geometry and alignment-conditioned structural support.

## Identity boundary

- Component: copy-retrieval-sscd
- Provider: sscd-disc-mixup-torchscript
- Source: the official SSCD copy-detection project and linked TorchScript artifact
- Preprocessing: SSCD_RGB_SHORTEST_SIDE_288_IMAGENET_NORMALIZATION_V1
- Exact runtime artifact SHA-256: 9f26bd4c848cc19b73d2ae92eea6e04886f61a7b764ceb7a13aeee62e6a6db56
- Current qualification: RUNTIME_READY

The selected local artifact is digest-bound. A replacement must use a new bundle
identity and pass the same runtime, terms, and evaluation gates.

## Outputs and semantics

The provider returns an embedding and cosine similarity for catalog ranking.
Similarity is not a posterior probability. Candidate rank is preserved separately
from pairwise verification rank.

## Known limits

- A global descriptor can confuse related composition, repeated graphics, and visual
  tradition.
- Retrieval recall must be measured on lawful target-domain transformations and hard
  negatives.
- A missing model degrades learned-required coverage; it cannot create a complete
  no-match.
- Terms for the exact artifact and intended event/product use require explicit review.

## Required promotion evidence

Exact artifact digest, locked runtime, clean-machine preflight, transform/source
disjoint retrieval report, hard-negative false-alert report, latency on the demo
machine, and a resolved terms record.
