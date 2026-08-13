# CreatorProof style-retrieval research map — 9 August 2026

This list intentionally keeps promising projects even when they are not suitable to vendor directly.
The integration question is scientific/engineering usefulness first: study the method, benchmark the
public artifacts where possible, and independently implement compatible ideas behind CreatorProof's
provider interface. Do not erase useful research from the roadmap merely because it is not the one-week
runtime default.

| Project | What CreatorProof should learn/use | v0.4 posture |
| --- | --- | --- |
| [CSD](https://github.com/learn2phoenix/CSD) / [paper](https://arxiv.org/abs/2404.01292) | Purpose-built contrastive style descriptors; style-vs-content motivation; artist prototype retrieval. | **Integrated as optional experimental learned provider.** External checkout/checkpoint only. Current upstream weight-discrepancy warning is surfaced. |
| [CSD+ analysis](https://arxiv.org/abs/2605.09030) | Shows why raw style cosine should not be treated as an absolute probability; discrimination-gap diagnostics and CSLS readout are the next calibration experiment. | **Benchmark methodology adopted.** Do not market raw cosine threshold as universal. Evaluate CSLS next. |
| [ALADIN](https://github.com/DanRuta/ALADIN) / [paper](https://arxiv.org/abs/2103.09776) | Fine-grained artistic-style embeddings; repository demonstrates embedding retrieval/clustering. Excellent independent challenger to CSD. | **Model-lab challenger.** Add an adapter and run the same creator-profile benchmark instead of trusting its dataset-specific reported score. |
| [StyleBabel](https://arxiv.org/abs/2203.05321) | Fine-grained human style language/tags linked to ALADIN-style representation. | **Explainability/taxonomy inspiration.** Future style descriptors should use human-understandable vocabulary without letting text labels manufacture similarity evidence. |
| [GOYA](https://github.com/yankungou/GOYA) / [paper](https://arxiv.org/abs/2304.10278) | Explicit content/style disentanglement and separate style-space retrieval. | **Research challenger.** Training recipe is far too heavy for the one-week prototype; use released research/evaluation ideas, not a from-scratch retrain. |
| [StyleDecoupler](https://arxiv.org/abs/2601.17697) | 2026 content/style disentanglement direction: isolate style from multimodal features using a unimodal content reference. | **Highest-priority research architecture.** No dependable official runnable code was found in this research pass, so do not fabricate an integration. |
| [WeART](https://huggingface.co/datasets/ZexiJia/WeART) | 2026 large-scale style benchmark (280K+ works, 152 styles, 1,556 artists) introduced with StyleDecoupler. | **Benchmark/reference corpus candidate.** Evaluate dataset terms and practical download size before use; never claim WeART performance without running it. |
| [OpenAI CLIP](https://github.com/openai/CLIP) | Semantic/multimodal baseline and a dependency of the upstream CSD architecture. | **Baseline/dependency.** Do not use vanilla CLIP similarity as the style verdict; compare it to style-specific models. |
| [DINOv2](https://github.com/facebookresearch/dinov2) | Strong self-supervised visual representation and content-heavy baseline; useful when testing whether a “style” method is still leaking subject/content. | **Negative/control baseline.** Measure content/style entanglement rather than assuming it. |
| [FAISS](https://github.com/facebookresearch/faiss) | Dense-vector similarity search and clustering when creator/work vectors outgrow exhaustive scan. | **Scale gate.** Unnecessary for the tiny hackathon catalog; add when retrieval latency/size justifies it. |
| [pytorch-grad-cam](https://github.com/jacobgil/pytorch-grad-cam) | CAM/ViT explainability methods, including image-similarity use cases. | **Explainability experiment.** Only promote a saliency view if it faithfully explains the chosen learned similarity target; a pretty heatmap is not evidence by itself. |
| [XFeat](https://github.com/verlab/accelerated_features) | Efficient learned local features for copy localization. | **Copy-lane tournament**, not style lane. |
| [LightGlue](https://github.com/cvg/LightGlue) | Learned sparse feature matching. | **Copy-lane tournament**, not style lane. |
| [RoMaV2](https://github.com/Parskatt/romav2) | Dense matching for difficult geometric localization. | **Copy-lane research**, not style lane. |
| [SAM 2](https://github.com/facebookresearch/sam2) | Segmentation from verified prompts can make copy evidence easier to inspect. | **Presentation experiment only.** A mask may refine a verified region; it must not create a match. |

## Recommended model tournament

Do not keep stacking models into one score. Compare candidates under the same contracts:

1. CSD raw cosine + creator prototypes.
2. CSD with the CSD+ corpus diagnostic; test CSLS as a readout correction.
3. ALADIN-ViT creator prototypes.
4. StyleDecoupler when an official/reproducible implementation becomes available.
5. Vanilla CLIP and DINO-family baselines to quantify content leakage.

Rank them on new-subject creator retrieval, difficult related-style negatives, creator-disjoint
generalization, latency/memory, and per-creator failures. Whichever wins becomes the provider; the
Evidence Packet and UI do not need to change.

## What not to borrow conceptually

- Do not make a single-image artist profile look statistically strong.
- Do not use image-to-image homography failure as evidence against style similarity.
- Do not turn a nearest neighbour into a binary match without a calibrated decision layer.
- Do not use generic VLM prose as the detector; language models may explain measured evidence but
  must not invent the measurement.
- Do not label a palette/texture heatmap “copied pixels.”

The target is an auditable multi-signal review API, not a visually impressive but semantically
incorrect detector demo.
