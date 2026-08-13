# CreatorProof v0.7 — repository, paper, dataset, and integration playbook

This playbook keeps promising technology visible without pretending every repository can be copied
into a commercial product. “Research-only” does not mean “discard”; it means study the method,
benchmark it through an isolated adapter, and obtain permission or implement the underlying public
idea independently before shipping.

## Status legend

- **SHIP CANDIDATE** — permissive project license identified; still verify model and dataset terms.
- **EXTERNAL ADAPTER** — run outside the core package and return the documented JSON contract.
- **RESEARCH / VERIFY** — promising, but no clear permissive code/weight license was confirmed.
- **BENCHMARK ONLY** — use for evaluation according to dataset terms, not as production weights.

No instruction below authorizes license circumvention. Changing variable names or rewriting a file
does not erase copyright or license obligations. For a restricted repository, use a clean-room
implementation from the paper's public method description or negotiate permission.

## 1. AI-generated-image detection

### Community Forensics — primary open detector

- Repository: https://github.com/JeongsooP/Community-Forensics
- Model: https://huggingface.co/OwensLab/commfor-model-384
- Status: **SHIP CANDIDATE** (MIT code/model card; confirm any downloaded data separately).
- Take: broad-generator ViT detector, official 384 px model, Random State Augmentation ideas,
  generator-community evaluation.
- Already integrated: safetensors-only local loader, transform probes, calibration registry.

Agent prompt:

```text
Integrate the official OwensLab/commfor-model-384 Community Forensics checkpoint as a local,
safetensors-only provider. Reproduce the upstream 384 px ImageNet-normalized preprocessing exactly,
record model file SHA-256 and provider version, never label sigmoid output as a probability, run the
provider over original/JPEG/resize/blur robustness views, and add a held-out calibration test. Do not
download training data or model files into source control.
```

### CO-SPY — independent semantic/pixel family

- Repository: https://github.com/Megum1/CO-SPY
- Paper family: CVPR 2025.
- Status: **SHIP CANDIDATE / EXTERNAL ADAPTER** (repository advertises MIT; verify every external
  backbone and weight artifact).
- Take: combine semantic and pixel-forensic evidence so one shortcut family does not dominate.

Agent prompt:

```text
Create an isolated CO-SPY inference wrapper from the official repository. Pin the upstream commit
and all weight hashes. The wrapper must accept one image path and print exactly one JSON object:
{"score":0..1,"provider":"co-spy","version":"<commit+weights>","calibrated":false,
"source_scope":"CO-SPY_EVALUATED_GENERATORS","warnings":[]}. Do not merge CO-SPY dependencies
into the core environment. Add generator-disjoint and JPEG robustness benchmarks before giving it
ensemble weight.
```

### SSP / ESSP — patch forensic candidate

- Repository: https://github.com/bcmi/SSP-AI-Generated-Image-Detection
- Status: **SHIP CANDIDATE / EXTERNAL ADAPTER** (MIT repository; verify checkpoint terms).
- Take: localized patch evidence; ESSP's reported compression/blur direction is especially relevant.
- Do not take: benchmark accuracy as evidence of open-world reliability.

Agent prompt:

```text
Wrap the official SSP inference path as an external JSON detector. Preserve upstream crop/patch
selection and normalization, pin model hash, aggregate patch logits transparently, and expose patch
dispersion as diagnostics. Test on unseen generators and social-media transforms. Keep calibrated=false
until a separate customer-domain calibration manifest is fitted. If ESSP code/weights are unavailable,
do not claim ESSP is active.
```

### B-Free — robustness training concept

- Repository: https://github.com/grip-unina/B-Free
- Status: **RESEARCH / VERIFY**. The repository's use conditions are not a default commercial grant.
- Take: semantically matched real/fake training pairs, degradation robustness, reduced content bias.
- If permission existed: benchmark the released model as another ensemble family.

Agent prompt:

```text
Read the B-Free paper and repository to specify a clean-room training-data recipe based on
semantically matched real/generated pairs and realistic post-processing. Do not copy restricted code
or redistribute weights. Implement the public algorithmic ideas independently behind CreatorProof's
SyntheticDetectorScore interface, document provenance for every training source, and compare it with
Community Forensics on a locked generator-disjoint test set.
```

### AIDE / Chameleon — sanity-check architecture

- Repository: https://github.com/shilinyan99/AIDE
- Paper: https://openreview.net/forum?id=ODRHZrkOQM
- Status: **RESEARCH / BENCHMARK ONLY** until code, weight, and Chameleon data terms are confirmed.
- Take: high-frequency and low-frequency patch selection, CLIP semantic stream, difficult benchmark.

Agent prompt:

```text
Use AIDE as a research comparison, not a bundled dependency. Recreate a clean ablation with
high-frequency patches, low-frequency patches, and a frozen semantic encoder; log each branch score
separately. Evaluate whether the branches add out-of-generator value over Community Forensics after
calibration. Do not include Chameleon assets in the CreatorProof distribution unless their terms
explicitly permit it.
```

### GAPL — generator-aware prototypes

- Repository: https://github.com/UltraCapture/GAPL
- Status: **RESEARCH / VERIFY**; no permissive license was confirmed during this audit.
- Take: generator-aware prototype learning and dynamic handling of heterogeneous fake sources.
- If permission existed: run as a second learned detector and report prototype attribution.

Agent prompt:

```text
Study GAPL's generator-aware prototype formulation and write an independent design note for a
prototype memory over known generator families plus an unknown-generator fallback. Do not copy code
or weights without permission. If an authorized installation is supplied by the operator, expose it
through the external JSON contract and validate that generator labels improve detection rather than
leaking dataset identity.
```

### PGC — score calibration research

- Repository: https://github.com/xiaoyu6868/PGC
- Paper: https://openreview.net/forum?id=yEjix8H6Dw
- Status: **RESEARCH / VERIFY**.
- Take: peak-guided calibration concept for cross-generator generalization.

Agent prompt:

```text
Reproduce PGC's calibration experiment as a separate research notebook using only authorized model
outputs. Compare PGC with CreatorProof's held-out Platt scaling on generator-disjoint validation.
Report ECE, Brier score, FPR@95TPR, and per-generator results. Promote it only if it improves locked
test calibration without reducing worst-generator discrimination.
```

### CLIDE — zero-shot domain branch

- Paper: https://openaccess.thecvf.com/content/WACV2026/papers/Betser_General_and_Domain-Specific_Zero-shot_Detection_of_Generated_Images_via_Conditional_WACV_2026_paper.pdf
- Status: **RESEARCH / VERIFY**.
- Take: explicit general versus domain-specific zero-shot conditioning.

Agent prompt:

```text
Prototype the public CLIDE method as a research-only external detector. Evaluate a general prompt
bank and a digital-art-specific prompt bank without tuning on the final test set. Return both scores
and their disagreement, and abstain when the domain-conditioned result is unstable. Do not add it to
production fusion until code/weight licensing and held-out performance are verified.
```

## 2. AI-origin datasets and benchmarks

### Community Forensics datasets

- Links are listed in the official repository.
- Status: **BENCHMARK/TRAINING SUBJECT TO DATA CARDS**.
- Take: broad generator coverage and CompEval methodology.

### RRDataset

- Repository: https://github.com/ChunXiaostudy/RRDataset
- Status: **BENCHMARK CANDIDATE**; verify each underlying source.
- Take: realistic reconstruction/relaundering robustness cases.

### So-Fake

- Repository: https://github.com/hzlsaber/So-Fake
- Status: **BENCHMARK CANDIDATE**.
- Take: social-media compression and explanation-focused evaluation.

### Kaggle Shutterstock/DeepMedia competition

- URL: https://www.kaggle.com/competitions/detect-ai-vs-human-generated-images
- Status: **BENCHMARK ONLY**, governed by competition/data terms.
- Take: diverse real/synthetic competition setup and community baselines.

### CIFAKE

- URL: https://www.kaggle.com/datasets/birdy654/cifake-real-and-ai-generated-synthetic-images
- Status: **SMOKE TEST ONLY**.
- Take: fast CI sanity and explainability experiments.
- Do not take: 32×32 CIFAR-10 versus Stable Diffusion 1.4 performance as evidence for modern art.

Dataset-agent prompt:

```text
Build a manifest-only benchmark loader; do not copy images into the repository. Deduplicate by
perceptual and exact hashes, group split by generator/source/lineage, reserve calibration and locked
test partitions, synthesize lawful JPEG/resize/blur/screenshot transforms, and report ROC-AUC, AP,
FPR@95TPR, TPR@1%FPR, abstention, selective accuracy, Wilson intervals, and worst-group results.
Label any run below the support gate SMOKE_TEST_ONLY.
```

## 3. Same-work copy and localization

### SSCD

- Repository: https://github.com/facebookresearch/sscd-copy-detection
- Status: **SHIP CANDIDATE** (MIT repository; model artifact stays external).
- Take: copy-detection descriptors, cosine retrieval, DISC-oriented evaluation.
- Already integrated: official TorchScript descriptor and explicit fallback state.

Agent prompt:

```text
Keep SSCD as global candidate retrieval, never as a standalone match verdict. Verify the official
model hash, L2 normalization, deterministic repeat output, transformed-query retrieval, hard
negatives, and exact re-ranking. At production scale add an ANN index, then exact cosine rerank the
shortlist before local verification.
```

### OpenCV SIFT/ORB + USAC/MAGSAC

- Repository: https://github.com/opencv/opencv
- Status: **SHIP CANDIDATE** (review OpenCV's bundled third-party notices).
- Take: SIFT/ORB descriptors, robust homography estimation, warping and diagnostics.

Agent prompt:

```text
Use mutual ratio-filtered local matches and USAC/MAGSAC. Validate minimum inliers, inlier ratio,
two-sided coverage, spatial dispersion, symmetric transfer error, and projected-corner sanity. Emit
no regions or correspondence lines when validation fails. After success, cluster only verified
inliers into compact support envelopes; label them feature-support regions, not copied-pixel masks.
```

### XFeat / LightGlue / RoMa / SAM 2 research lane

- XFeat: https://github.com/verlab/accelerated_features
- LightGlue: https://github.com/cvg/LightGlue
- RoMa: https://github.com/Parskatt/RoMa
- SAM 2: https://github.com/facebookresearch/sam2
- Status: **MODEL TOURNAMENT / VERIFY LICENSES AND WEIGHTS**.
- Take: stronger correspondences, dense matching, optional semantic mask presentation.
- Do not take: a segmentation mask as proof of copying.

Agent prompt:

```text
Add each matcher behind the existing GeometryVerifier contract and benchmark it against SIFT/ORB on
the same positive and hard-negative pairs. Keep identical fail-closed gates. Promote only a model
that improves partial-copy recall without increasing repeated-pattern false positives. Use SAM 2
only to refine presentation around already-verified support, never to create evidence by itself.
```

## 4. Creator-style attribution and similarity

### CSD

- Repository: https://github.com/learn2phoenix/CSD
- Status: **SHIP CANDIDATE WITH CHECKPOINT CAUTION** (MIT code; pin and verify weights).
- Take: content/style-separated descriptors.
- Already integrated: optional external runtime, profile pooling, content controls.

Agent prompt:

```text
Keep CSD optional and hash-pinned. Never enable legacy pickle loading without an exact expected
SHA-256. Form creator profiles from multiple diverse works, compute catalog density correction,
leave-one-out cohesion, cross-creator negative tails, and content control. Never infer a creator from
one exemplar or call raw cosine a probability.
```

### IntroStyle

- Repository: https://github.com/AnandK27/introstyle
- Paper: https://openaccess.thecvf.com/content/ICCV2025/papers/Kumar_IntroStyle_Training-Free_Introspective_Style_Attribution_using_Diffusion_Features_ICCV_2025_paper.pdf
- Status: **RESEARCH / VERIFY**; no clear permissive repository license was confirmed.
- Take: training-free style descriptors from diffusion-model internal features.
- If permission existed: compare its profile discrimination with CSD on creator-disjoint data.

Agent prompt:

```text
Study IntroStyle's diffusion-feature extraction and independently implement the paper's public
method behind a style-embedding adapter only if dependencies permit. Do not copy unlicensed code.
Run a creator-disjoint tournament against CSD using same-creator/different-content positives and
same-movement hard negatives. Compare top-1, FAR, EER, profile-size sensitivity, GPU memory, and
latency before promotion.
```

### DiffSim

- Repository: https://github.com/showlab/DiffSim
- Status: **RESEARCH / VERIFY**; no permissive license was confirmed during this audit.
- Take: diffusion-feature similarity as a complementary relational signal.

Agent prompt:

```text
Evaluate DiffSim's public paper idea in an isolated research adapter. Do not treat it as a direct
style probability. Test whether it adds creator discrimination after controlling subject/content
with SSCD. Promote only if a nested cross-validation experiment improves worst-creator false accept
rate over CSD alone.
```

### MCID

- Paper: https://openaccess.thecvf.com/content/ICCV2025/papers/Huang_MCID_Multi-aspect_Copyright_Infringement_Detection_for_Generated_Images_ICCV_2025_paper.pdf
- Status: **RESEARCH FRAMEWORK**.
- Take: separate content, style, structure, and emotion/aspect evidence instead of one similarity.

Agent prompt:

```text
Map MCID's multi-aspect formulation onto CreatorProof as an evaluation ontology. Keep content/copy,
structure, and style scores separate in the API; treat emotion as an optional descriptive feature.
Do not train a single “infringement” classifier. Build ablations showing which independent evidence
family changes each decision and retain human-policy review as the final step.
```

## 5. Provenance, watermarking, and proof

### C2PA / c2pa-rs / c2patool

- Specification: https://spec.c2pa.org/specifications/specifications/2.4/specs/C2PA_Specification.html
- Repository: https://github.com/contentauth/c2pa-rs
- Status: **SHIP CANDIDATE** (official open implementation; follow trust-list guidance).
- Already integrated: safe subprocess inspection and explicit trusted/untrusted/missing states.

Agent prompt:

```text
Install an official c2patool release, pin its version/hash, inspect assets without a shell, preserve
manifest validity separately from signer trust, expose only a privacy-minimized summary, and map
generative actions to AI-provenance evidence. Missing metadata must remain UNKNOWN. Add fixtures for
trusted, untrusted, tampered, absent, timeout, and malformed outputs.
```

### SynthID and provider watermarks

- Overview: https://deepmind.google/models/synthid/
- Status: **PROVIDER-INTEGRATION RESEARCH**, not an open universal detector.
- Take: detectable provenance marks are stronger when a provider offers a verified detector.

Agent prompt:

```text
Add a WatermarkEvidence provider contract with provider name, verification state, model/tool version,
and signed receipt where available. Do not build a visual imitation of SynthID or claim to detect a
private watermark. Fuse a verified provider mark as provenance evidence, not as pixel-model voting.
```

### Ethereum Attestation Service

- Site: https://attest.org/
- Contracts: https://github.com/ethereum-attestation-service/eas-contracts
- SDK: https://github.com/ethereum-attestation-service/eas-sdk
- Status: **SHIP CANDIDATE** (MIT repositories; choose a supported network).
- Already integrated: direct on-chain `bytes32 packetHash` attestation and receipt validation.

Agent prompt:

```text
Register or verify an EAS schema exactly equal to `bytes32 packetHash`. Configure a testnet EAS
contract, schema UID, funded demo signer, RPC, recipient, chain ID, and explorer base URL. Submit only
the canonical Evidence Packet SHA-256, wait for a successful receipt, parse the Attested UID, call
isAttestationValid, and display the explorer link. Never put raw media, claimant names, detector
scores, or API keys on-chain.
```

### Batch-root production upgrade

Agent prompt:

```text
Extend the local Merkle log with signed immutable checkpoints. At a fixed interval, attest one tree
root and tree size through EAS. Return each scan's packet hash, leaf index, inclusion path, checkpoint
signature, and EAS receipt. Verify the entire chain locally. This keeps evidence private and reduces
public transaction cost while preserving third-party auditability.
```

## 6. Market and product references

These are competitive/product references, not sources for model-accuracy claims.

- Hive AI detection API: https://docs.thehive.ai/docs/ai-generated-content-detection
- Truepic: https://www.truepic.com/
- Content Credentials: https://contentcredentials.org/
- C2PA coalition: https://c2pa.org/

Take the product pattern: API-first scanning, provenance display, clear classifications, enterprise
workflows, and trust/audit infrastructure. CreatorProof differentiates through customer-declared
protected catalogs and the independent origin/copy/style evidence model.

## 7. External detector contract

Configure authorized research providers without contaminating the core environment:

```dotenv
CREATORPROOF_SYNTHETIC_EXTERNAL_DETECTORS_JSON=[{"name":"co-spy","command":"python /absolute/path/co_spy_adapter.py {image}","timeout_seconds":45}]
```

The command is parsed without a shell and must print one JSON object:

```json
{
  "score": 0.82,
  "provider": "co-spy",
  "version": "commit-or-weight-hash",
  "calibrated": false,
  "source_scope": "RECORDED_EVALUATION_GENERATORS",
  "warnings": ["RESEARCH_MODEL"]
}
```

Required promotion sequence:

1. deterministic runtime check;
2. model and preprocessing hash record;
3. generator-disjoint benchmark;
4. transform robustness;
5. held-out calibration;
6. complementary-error analysis versus existing members;
7. latency/memory measurement;
8. license and model-card review;
9. only then assign ensemble weight.

Adding more correlated models without this sequence can make the system slower and more
overconfident, not more accurate.
