# CreatorProof v0.5 — research and repository map

Snapshot: 9 August 2026.

This map intentionally retains promising projects even when they are not the one-week default. Study,
benchmark, or place them behind a provider boundary. CreatorProof should not pretend an optional project
is integrated until its exact model/checkpoint passes the same local benchmark.

## Copy retrieval, verification, and perceptual similarity

| Project | Primary source | Best use in CreatorProof | v0.5 posture |
| --- | --- | --- | --- |
| SSCD | [paper](https://openaccess.thecvf.com/content/CVPR2022/html/Pizzi_A_Self-Supervised_Descriptor_for_Image_Copy_Detection_CVPR_2022_paper.html) / [repo](https://github.com/facebookresearch/sscd-copy-detection) | Global image-copy descriptor and catalog retrieval. | **Active** when local TorchScript artifact is present. |
| DISC21 / ISC2021 | [challenge repo](https://github.com/facebookresearch/isc2021) / [dataset](https://ai.meta.com/datasets/disc21-dataset/) | Large-scale copy benchmark; transformation taxonomy; global-to-pairwise verification mindset. | **Benchmark blueprint.** |
| D2LV | [paper](https://arxiv.org/abs/2111.07090) / [repo](https://github.com/WangWenhao0716/ISC-Track1-Submission) | Winning ISC matching-track ideas: global/local and local/global verification, difficult crops/overlays, score ensembles. | **Architecture inspiration.** Do not vendor source into core. |
| DreamSim | [repo](https://github.com/ssundaram21/dreamsim) / [paper](https://arxiv.org/abs/2306.09344) | Human-aligned mid-level perceptual re-ranker for top-K pairs. | **High-priority optional challenger.** |
| DiffSim | [ICCV 2025 paper](https://openaccess.thecvf.com/content/ICCV2025/html/Song_DiffSim_Taming_Diffusion_Models_for_Evaluating_Visual_Similarity_ICCV_2025_paper.html) / [repo](https://github.com/showlab/DiffSim) | Diffusion-attention visual similarity spanning appearance/style/instance cues. | **GPU/CPU research re-ranker.** Benchmark cost before API promotion. |
| LPIPS | [CVPR 2018 paper](https://openaccess.thecvf.com/content_cvpr_2018/html/Zhang_The_Unreasonable_Effectiveness_CVPR_2018_paper.html) / [repo](https://github.com/richzhang/PerceptualSimilarity) | Learned full-reference perceptual baseline after alignment. | **Metric tournament.** |
| DISTS | [paper](https://arxiv.org/abs/2004.07728) / [repo](https://github.com/dingkeyan93/DISTS) | Structure/texture-aware full-reference perceptual baseline. | **Metric tournament.** |
| GMSD | [paper](https://arxiv.org/abs/1308.3052) | Efficient gradient-structure degradation signal. | **Concept active:** v0.5 uses its own alignment-conditioned gradient-similarity family, not vendored implementation. |
| OpenCV | [geometric transforms/docs](https://docs.opencv.org/4.13.0/d2/d75/namespacecv.html) | SIFT/ORB, USAC/MAGSAC homography, warps, deterministic CPU structural math. | **Active.** |

## Stronger local/dense matching candidates

| Project | Primary source | Why keep it | Promotion test |
| --- | --- | --- | --- |
| XFeat | [CVPR 2024 repo](https://github.com/verlab/accelerated_features) | Efficient learned local features; attractive CPU-oriented challenger. | Recall vs hard-negative false verification vs latency. |
| LightGlue | [ICCV 2023 repo](https://github.com/cvg/LightGlue) | Learned sparse feature matcher compatible with several feature families. | Same pair benchmark behind current geometry contract. |
| RoMa | [CVPR 2024 repo](https://github.com/Parskatt/RoMa) | Dense robust matching for hard appearance changes. | Localization quality and compute cost. |
| RoMaV2 | [repo](https://github.com/Parskatt/romav2) | Newer dense matcher direction. | Research challenger; verify dependency/checkpoint terms independently. |
| OmniGlue | [CVPR 2024 repo](https://github.com/google-research/omniglue) | Foundation-model-guided matching aimed at out-of-domain generalization. | Archived upstream, but still a useful reproducibility/challenger baseline. |
| MATCHA | [CVPR 2025 repo](https://github.com/nv-dvl/matcha) | Joint geometric and semantic correspondence; useful when purely local texture matches are insufficient. | Highest-priority heavy matcher experiment. |
| EDM | [ICCV 2025 repo](https://github.com/chicleee/EDM) | Efficient dense matching; published ONNX path makes deployment experiments interesting. | Measure CPU/GPU latency and false geometry. |
| GIM | [ICLR 2024 repo](https://github.com/xuelunshen/gim) | Generalizable image matching/training framework. | Training-heavy research path rather than hackathon default. |

## Artistic style and cross-content similarity

| Project | Primary source | Best use | v0.5 posture |
| --- | --- | --- | --- |
| IntroStyle | [ICCV 2025 paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Kumar_IntroStyle_Training-Free_Introspective_Style_Attribution_using_Diffusion_Features_ICCV_2025_paper.pdf) / [repo](https://github.com/AnandK27/introstyle) | Training-free diffusion-feature style attribution with content-diverse style evaluation. | **Top style challenger.** Keep external until its dependency/model path is benchmarked end-to-end. |
| DiffSim | [repo](https://github.com/showlab/DiffSim) | Human-oriented style/instance similarity from diffusion features. | **Second top style challenger** and perceptual re-ranker. |
| CSD | [paper](https://arxiv.org/abs/2404.01292) / [repo](https://github.com/learn2phoenix/CSD) | Style-specific descriptor and creator prototype retrieval. | **Optional active provider**, explicitly experimental because upstream still warns about uploaded-weight discrepancy. |
| CSD+ | [2026 preprint](https://arxiv.org/abs/2605.09030) | Evidence that raw style cosine can need corpus-aware normalization; CSLS-style readout experiment. | **Research/calibration idea; preprint, not peer-reviewed here.** |
| ALADIN | [ICCV 2021 paper](https://openaccess.thecvf.com/content/ICCV2021/html/Ruta_ALADIN_All_Layer_Adaptive_Instance_Normalization_for_Fine-Grained_Style_Similarity_ICCV_2021_paper.html) / [repo](https://github.com/DanRuta/ALADIN) | Fine-grained artistic style representation independent of current CSD stack. | **Independent model challenger.** |
| StyleBabel | [paper](https://arxiv.org/abs/2203.05321) | Human style terminology and fine-grained style-language mapping. | **Explanation/taxonomy research.** |
| GOYA | [repo](https://github.com/yankungou/GOYA) / [paper](https://arxiv.org/abs/2304.10278) | Explicit content/style disentanglement direction. | **Research challenger; training too heavy for default.** |
| Gatys neural style | [CVPR 2016 paper](https://openaccess.thecvf.com/content_cvpr_2016/html/Gatys_Image_Style_Transfer_CVPR_2016_paper.html) | Feature-correlation/Gram-matrix view of texture/style. | **Mathematical/background inspiration.** |
| AdaIN | [ICCV 2017 paper](https://openaccess.thecvf.com/content_iccv_2017/html/Huang_Arbitrary_Style_Transfer_ICCV_2017_paper.html) | Channel statistics as a style representation. | **Mathematical/background inspiration.** |
| StyleDecoupler | [2026 preprint](https://arxiv.org/abs/2601.17697) | Explicit content/style decoupling and creator/style benchmark direction. | **Future research; preprint status must stay visible.** |
| WeART | [dataset](https://huggingface.co/datasets/ZexiJia/WeART) | Large style/artist evaluation corpus associated with StyleDecoupler. | **Benchmark candidate; evaluate dataset terms and domain fit first.** |
| CLIP | [repo](https://github.com/openai/CLIP) | Semantic/content-heavy control baseline. | **Control, not style verdict.** |
| DINOv2 | [repo](https://github.com/facebookresearch/dinov2) | Strong self-supervised visual baseline for measuring content leakage. | **Control/challenger.** |

## Generative-model copying, memorization, and data attribution

These papers explain why CreatorProof must not equate “looks AI-generated” with “copied this registered
work.” The scientifically useful question is whether a generated asset can be attributed to or derived
from a source under a defined experimental setting.

| Work | Primary source | CreatorProof lesson |
| --- | --- | --- |
| Latent Diffusion | [CVPR 2022](https://openaccess.thecvf.com/content/CVPR2022/html/Rombach_High-Resolution_Image_Synthesis_With_Latent_Diffusion_Models_CVPR_2022_paper.html) | Modern diffusion generation works in learned latent representation; generator artifacts are not a stable source-identity test. |
| DiT | [ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/html/Peebles_Scalable_Diffusion_Models_with_Transformers_ICCV_2023_paper.html) | Modern diffusion denoisers need not be U-Nets; do not hard-code “AI fingerprints” to one architecture. |
| Diffusion Art or Digital Forgery? | [CVPR 2023](https://openaccess.thecvf.com/content/CVPR2023/html/Somepalli_Diffusion_Art_or_Digital_Forgery_Investigating_Data_Replication_in_Diffusion_CVPR_2023_paper.html) | Diffusion models can replicate training content; retrieval/copy descriptors are useful for replication studies. |
| Evaluating Data Attribution for T2I | [ICCV 2023](https://openaccess.thecvf.com/content/ICCV2023/papers/Wang_Evaluating_Data_Attribution_for_Text-to-Image_Models_ICCV_2023_paper.pdf) / [repo](https://github.com/peterwang512/gendataattribution) | Data attribution is distinct from ordinary copy detection when generation changes content substantially. |
| Detecting/Explaining/Mitigating Memorization | [ICLR 2024](https://openreview.net/forum?id=84n3UwkH7b) | Memorization needs model/data-aware measurement rather than a generic “AI detector.” |
| Region-Level Data Attribution | [ICCV 2025 paper](https://openaccess.thecvf.com/content/ICCV2025/papers/Nguyen_Region-Level_Data_Attribution_for_Text-to-Image_Generative_Models_ICCV_2025_paper.pdf) / [repo](https://github.com/AIoT-Lab-BKAI/AR-Detector) | Region-level attribution is a future model-access lane when generation-source evidence is available. |

## Scale, explainability, provenance, and proof

| Project | Link | Posture |
| --- | --- | --- |
| FAISS | https://github.com/facebookresearch/faiss | Move SSCD/style vector search from exhaustive scan to ANN when catalog scale warrants it. |
| Qdrant | https://github.com/qdrant/qdrant | Alternative production vector store with filtering/metadata. |
| pytorch-grad-cam | https://github.com/jacobgil/pytorch-grad-cam | Explainability experiment only when it faithfully explains the selected learned target. |
| SAM 2 | https://github.com/facebookresearch/sam2 | May refine a *verified* region for presentation; segmentation must never create match evidence. |
| C2PA | https://github.com/contentauth/c2pa-rs | Signed provenance/manifest verification provider; independent of visual similarity. |
| EAS | https://github.com/ethereum-attestation-service/eas-contracts | On-chain attestation/receipt provider for evidence commitments, not a detector. |

## Recommended one-week model tournament

1. Keep SSCD + v0.5 SIFT/ORB/MAGSAC + aligned structural fusion as the CPU-safe baseline.
2. Benchmark XFeat and MATCHA behind the same local-verifier contract; promote only if held-out recall
   improves without unacceptable hard-negative false verification.
3. Benchmark DreamSim and DiffSim as top-K perceptual re-rankers. They must add measurable value beyond
   the aligned structural verifier before becoming API-default dependencies.
4. Benchmark IntroStyle against CSD, ALADIN, CLIP, and DINO controls on creator-disjoint, new-subject
   artwork. Report content leakage explicitly.
5. Add ANN only after catalog scale makes exhaustive SSCD retrieval a measured bottleneck.
6. Keep C2PA and chain attestation orthogonal: provenance and immutable receipts strengthen auditability;
   neither makes a similarity score more accurate.
