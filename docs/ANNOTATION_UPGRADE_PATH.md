# Annotation upgrade path

CreatorProof v0.4 separates copy localization from creator-style retrieval. Inside the **copy lane**
it deliberately separates three problems:

1. **retrieval** — SSCD ranks registered source candidates;
2. **verification** — local correspondences plus robust geometry decide whether localization evidence
   is trustworthy enough to expose;
3. **visualization** — the Evidence Microscope explains only evidence that survived verification.

The copy runtime improves visualization without introducing another unbenchmarked local model: one global
convex-hull annotation is replaced by compact local support envelopes, correspondence lines are
hover-first, and every stored pair includes transfer error.

The learned-local-verifier candidates below are copy-lane technologies, not style detectors. The
independent style-model tournament is documented in `STYLE_RESEARCH_REPOS.md`.

## Learned-local-verifier tournament

Do not replace the deterministic ORB verifier solely because a newer model looks better in a demo.
Benchmark each candidate on CreatorProof's transformed-copy and hard-negative corpus, then promote the
winner behind the same fail-closed evidence contract.

| Candidate | Why it is relevant | Integration posture |
| --- | --- | --- |
| [XFeat](https://github.com/verlab/accelerated_features) | Official CVPR 2024 implementation supports sparse and semi-dense local matching and explicitly targets efficient CPU inference. Repository license is Apache-2.0. | Best first learned-verifier experiment for the one-week/demo constraint. |
| [LightGlue](https://github.com/cvg/LightGlue) | Official ICCV 2023 matcher accepts sparse local features and publishes pretrained configurations for several feature families. Repository license is Apache-2.0. | Tournament against XFeat where extra matcher cost is acceptable. |
| [RoMaV2](https://github.com/Parskatt/romav2) | Official implementation exposes dense matches and sampling for robust estimation. | Research/high-accuracy lane; benchmark compute. Repository notes MIT code except the DINOv3 dependency, which has its own license. |
| [SAM 2](https://github.com/facebookresearch/sam2) | Promptable image/video segmentation can turn verified point/box prompts into masks. | Optional presentation experiment only. Never treat a SAM mask as proof of shared pixels or let segmentation create a match. |

## Promotion requirements

A learned verifier must beat the current verifier on the project corpus for the operating point that
matters, not just increase match count. Record at least:

- transformed-copy verification recall;
- hard-negative false-verification rate;
- localization/overlap quality for a hand-labeled subset;
- p50/p95 latency and memory on demo hardware;
- behavior on crops, screenshots, perspective changes, overlays, collages, repeated patterns, text,
  illustrations, and texture-poor images;
- failure examples and abstention rate.

Regardless of provider, the visualization contract remains: rejected evidence emits no annotation;
verified point support is not automatically a semantic object mask; nearest retrieval is not local
verification.
