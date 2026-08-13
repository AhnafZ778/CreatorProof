# CreatorProof v0.6 research and model tournament

Date: 9 August 2026. Technical claims below link to primary papers or official repositories.

## Active now

| Technology | What CreatorProof uses | Status |
| --- | --- | --- |
| [CSD](https://arxiv.org/abs/2404.01292) / [official repo](https://github.com/learn2phoenix/CSD) | Learned style descriptor, creator anchor pools | Optional experimental provider; exact checkpoint must be pinned |
| [CSD+](https://arxiv.org/abs/2605.09030) | CSLS catalog readout and discrimination-gap diagnostic | Active readout; preprint status remains visible |
| [SSCD](https://github.com/facebookresearch/sscd-copy-detection) | Near-copy retrieval plus content-confound control | Active when official TorchScript artifact is present |
| OpenCV | Transparent edge, texture, tile diagnostics; robust copy geometry | Active, but never treated as semantic style attribution |

The repository does not copy external source trees or weights. It implements documented math and adapters
around operator-supplied, pinned runtimes.

## Highest-priority challenger tournament

| Challenger | Primary source | Why it matters | Promotion requirement |
| --- | --- | --- | --- |
| IntroStyle | [ICCV 2025 paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Kumar_IntroStyle_Training-Free_Introspective_Style_Attribution_using_Diffusion_Features_ICCV_2025_paper.pdf), [official repo](https://github.com/AnandK27/introstyle) | Training-free diffusion features designed for style attribution | Pin model/layer/timestep; repair and document repo setup; beat CSD+ on creator-disjoint hard negatives |
| DiffSim | [ICCV 2025 paper](https://openaccess.thecvf.com/content/ICCV2025/html/Song_DiffSim_Taming_Diffusion_Models_for_Evaluating_Visual_Similarity_ICCV_2025_paper.html), [official repo](https://github.com/showlab/DiffSim) | Diffusion-attention similarity aligned to human judgments, with style benchmark | Measure GPU/CPU latency and VRAM; use as second-stage reranker only if accuracy gain justifies cost |
| ALADIN-ViT | [ICCV 2021 paper](https://openaccess.thecvf.com/content/ICCV2021/html/Ruta_ALADIN_All_Layer_Adaptive_Instance_Normalization_for_Fine-Grained_Style_Similarity_ICCV_2021_paper.html), [official repo](https://github.com/DanRuta/ALADIN) | Independent fine-grained style embedding and released inference weights | Run identical manifest and report license/artifact identity, top-1, AUC, FPR, latency |
| StyleBabel | [paper](https://arxiv.org/abs/2203.05321) | Human style vocabulary and tagging | Explanation-only until tag accuracy and bias are validated |
| GOYA | [paper](https://arxiv.org/abs/2304.10278), [repo](https://github.com/yankungou/GOYA) | Explicit content/style separation | Research branch; do not add training cost to one-week demo |
| DINOv2 | [official repo](https://github.com/facebookresearch/dinov2) | Strong semantic/content control | Negative/control baseline, not the style verdict |
| CLIP | [official repo](https://github.com/openai/CLIP) | Semantic baseline and CSD dependency | Control for subject leakage, not a creator attribution model |

## Exact agent prompts for each challenger

### IntroStyle

> Create an isolated `research/introstyle` adapter around the official IntroStyle repository. Do not
> alter the production provider. Pin the repository commit, diffusion model revision, timestep, layer,
> preprocessing, dtype, device, and output normalization. Run the CreatorProof creator-disjoint style
> manifest and export top-1, recall@5, pair ROC-AUC, EER, per-creator FPR, latency, peak VRAM, and every
> failed query. Do not claim activation unless real inference succeeds. Do not promote unless it improves
> hard-negative FPR at equal recall over CSD+ on at least three random creator-disjoint splits.

### DiffSim

> Integrate the official DiffSim repository only as an offline top-N style reranker. Pin the commit and
> base diffusion model. Rerank the CSD+ top 10 profiles and compare against CSD+ alone on Sref-like
> different-content positives and same-movement negatives. Record CPU/GPU latency and memory. Fail closed
> when the model is unavailable. Promote only if the measured gain is stable and API latency remains inside
> the declared service budget.

### ALADIN-ViT

> Build an external ALADIN-ViT style embedding adapter using the official inference example and released
> checkpoint. Never paste or relicense upstream code into CreatorProof. Pin source and weight digests,
> normalize embeddings, reuse the same creator-pool/CSLS/discrimination benchmark, and compare raw and
> catalog-corrected readouts. Report domain shift and do not reuse the repository's dataset accuracy as a
> CreatorProof accuracy claim.

## Benchmark composition

Use at least:

- 10–20 representative anchors per creator where possible;
- three or more creators per nearby movement/visual tradition;
- held-out different-subject positives;
- same-subject/different-style controls;
- same-palette/different-mark-making controls;
- AI-generated style-prompt positives only when prompt and generator provenance are known;
- image-to-image retouches in the copy benchmark, not as substitutes for style positives.

Splits must be creator-disjoint for generalization claims. Report per-creator results because a high global
average can hide catastrophic failure for one visual tradition.

## What is deliberately not promised

No current model can be made “perfect” by increasing one score. Style is subjective, labels are noisy,
different artists share traditions, and legal infringement is jurisdiction- and fact-dependent. The product
claim should be: **catalog-scoped, auditable risk evidence with calibrated human-review routing**.

