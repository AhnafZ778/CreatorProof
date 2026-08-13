# Model card: Community Forensics 384

## Role

Community Forensics supplies passive pixel evidence for the AI-origin lane. It is
independent from copy and creator-profile evidence. Quiet output never proves human
origin, and high output never establishes authorship, generator identity, training
data, or legal status.

## Identity boundary

- Component: origin-community-forensics
- Provider: community-forensics-vit-small-384
- Repository: OwensLab/commfor-model-384
- Preprocessing: COMMUNITY_FORENSICS_SHORT_SIDE_440_CENTER_CROP_384_V1
- Repository revision: 6076002bf0d9dd37537f965ee2f06f826c333b61
- Safetensors SHA-256: b89f36275f3bf5e2b040eee36597a8f19db051bff9a473a9cf7b2466284fb387
- Current qualification: RUNTIME_READY

## Runtime safeguards

The provider accepts exactly one safetensors artifact, records its SHA-256 and
preprocessing identity, and rejects a configured digest mismatch. Multi-view delivery
transforms and spatial crops are aggregated separately. Detector errors stay visible.

## Calibration boundary

Raw scores are not probabilities. A Platt fit applies only when provider, model
version, artifact digest, preprocessing, domain, crop policy, and minimum support
counts match. Any drift returns the raw score with an explicit mismatch state.

## Known limits

Open-world generators, editing, resizing, compression, screenshots, and domain shift
can invalidate measured behavior. Model/checkpoint terms and training/evaluation data
terms are separate review items.

## Required promotion evidence

Terms approval, generator- and source-disjoint authorized corpus, per-transform and per-generator metrics,
calibration and abstention analysis, and demo-machine runtime evidence.
