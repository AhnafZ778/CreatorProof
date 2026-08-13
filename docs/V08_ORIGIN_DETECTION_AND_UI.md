# CreatorProof v0.8 — origin detection correction and clear-result UI

Build signature: `CLEAR-ORIGIN-ENSEMBLE-2026.08.09`

## Executive result

v0.8 fixes two different defects that v0.7 accidentally presented as one problem:

1. the Community Forensics checkpoint was receiving the wrong image transform; and
2. a raw, uncalibrated detector output was rendered like a percentage.

The first defect could suppress a real model response, especially on non-square artwork. The second
could turn that suppressed signal into a misleading statement such as “1% AI.” v0.8 corrects the
official preprocessing contract, introduces multi-crop and evidence-family fusion, refuses negative
clearance from one uncalibrated model, and removes raw origin percentages from the default UI.

This is a better prototype, not a universal AI-image oracle. Accuracy still has to be measured on a
generator-, source-, and transformation-disjoint corpus matching the intended customer domain.

## Root-cause audit

| v0.7 behavior | Why it failed | v0.8 correction |
| --- | --- | --- |
| Force-fit every input to 384×384 | The official Community Forensics evaluation path resizes the shorter side to 440 and center-crops 384 | Match the upstream evaluation transform exactly |
| Render `fused_detector_score` with a percent sign | The field is explicitly not a calibrated probability | No score in the default result; expose a domain score only after complete held-out calibration |
| Permit one low uncalibrated model to return no-AI evidence | One detector can miss unseen generators, edits, or domains | Abstain unless at least two independent calibrated evidence families support a quiet result |
| Count detector instances rather than signal families | Similar checkpoints can create fake corroboration | Group members by declared evidence family before fusion |
| Reduce a large artwork to one global model crop | Local generator traces can disappear during reduction | Add five overlapping spatial crops; require multi-crop consensus before any uplift |
| Put scores, codes, ledgers, and diagnostics above the answer | Users could not identify the decision or next action | Show one bottom line, three plain lane cards, and an expandable technical section |

## Active origin pipeline

```text
uploaded image
   |
   +-- official C2PA inspection ----------------------> trusted AI assertion?
   |
   +-- delivery views: original / JPEG / resize / blur
   |        |
   |        +-- Community Forensics (semantic/generalization family)
   |        +-- GRIP CLIPDet adapter (semantic+pixel hybrid family, optional)
   |        +-- operator adapters (family must be declared)
   |
   +-- spatial views: center + four overlapping corners
            |
            +-- multi-crop consensus (one hot crop cannot decide)

per-detector robust score
   -> group by evidence family
   -> family-level quality/stability weighting
   -> disagreement, resolution, calibration, and coverage gates
   -> likely / review / quiet / unknown / unavailable
   -> plain-language presentation contract
```

## Correct model preprocessing

For the 384-input Community Forensics model, v0.8 applies:

1. EXIF orientation normalization;
2. RGB conversion;
3. resize the shorter side to 440 with bilinear interpolation;
4. center-crop 384×384;
5. scale pixels to `[0,1]`;
6. ImageNet mean/std normalization.

This matches the upstream `dataloader.get_transform(..., mode="test")` path. The implementation is
regression-tested with a non-square image so a future refactor cannot silently return to force-fit
distortion.

Primary implementation references:

- [Community Forensics official repository](https://github.com/JeongsooP/Community-Forensics)
- [Official evaluation notebook](https://github.com/JeongsooP/Community-Forensics/blob/main/eval_using_huggingface.ipynb)
- [Official dataloader and transform](https://github.com/JeongsooP/Community-Forensics/blob/main/dataloader.py)
- [Official 384 safetensors model](https://huggingface.co/OwensLab/commfor-model-384)

## Detection math

### 1. Delivery robustness

For detector `d`, view scores `s(d,v)` are combined in log-odds space:

```text
g_d = sigmoid( sum_v w_v logit(s(d,v)) / sum_v w_v )
```

The standard deviation is computed only over delivery transformations, not spatial crops:

```text
stability_d = max(0, 1 - std_v(s(d,v)) / configured_max_std)
```

This prevents spatial diversity from being mislabeled as delivery instability.

### 2. Multi-crop consensus

The image yields center, top-left, top-right, bottom-left, and bottom-right crops at a configurable
fraction (default `0.78`). Let their calibrated or raw signals be `c(d,j)`.

```text
m_d = median_j c(d,j)
```

Spatial support is accepted only if at least three distinct crops reach the review operating point.
Then:

```text
a_d = max(g_d, m_d)
```

Otherwise `a_d = g_d`. A single hot crop cannot raise the detector result.

### 3. Evidence-family fusion

Every detector declares an evidence family, for example:

- `SEMANTIC_GENERATOR_GENERALIZATION` for Community Forensics;
- `SEMANTIC_PIXEL_HYBRID` for the official GRIP two-model adapter;
- an operator-defined family for another authorized adapter.

Members inside the same family are fused first. Only the resulting family scores enter the final
ensemble. This prevents three similar checkpoints from being counted as three independent kinds of
evidence.

Uncalibrated members receive a reliability discount. Stability modifies reliability; it never turns
a raw score into a probability.

### 4. Positive and quiet decision gates

A model-only `LIKELY_AI_GENERATED` result requires:

- at least the configured minimum independent families (default two);
- at least two stable families above the likely operating point;
- a fused score above that operating point;
- no resolution, instability, or disagreement abstention.

A quiet `NO_AI_ORIGIN_EVIDENCE_DETECTED` result requires:

- at least two independent families;
- every deciding family to have held-out, model-version-matched calibration;
- every family below the review operating point.

One raw 0.01 response therefore becomes `AI_ORIGIN_INCONCLUSIVE_LIMITED_COVERAGE`, never “1% AI” and
never proof of human origin.

### 5. Provenance precedence

A trusted C2PA AI assertion can produce `AI_PROVENANCE_CONFIRMED`. An assertion from an untrusted
signer routes review. Missing Content Credentials remain unknown; they are not negative AI evidence.

## Complementary model strategy

v0.8 includes a clean adapter for the official GRIP CLIP-based detector. It calls an operator-installed
copy of the Apache-2.0 repository, reads the repository's own `soft_or_prob` fused signed
log-likelihood-ratio output, maps that fused value through a sigmoid only to produce a bounded raw
signal, and still requires CreatorProof's deployment
calibration registry before any calibrated semantics are attached.

Primary references:

- [GRIP CLIP-based synthetic-image detection](https://github.com/grip-unina/ClipBased-SyntheticImageDetection)
- [CO-SPY: semantic and pixel features](https://github.com/Megum1/CO-SPY)
- [AIDE: hybrid semantic and low-level artifacts](https://github.com/shilinyan99/AIDE)

Community Forensics plus GRIP CLIPDet is the recommended near-term demo pair because both have
official code/checkpoints and commercially usable repository licenses. CO-SPY and AIDE remain model
tournament candidates; do not add them to production fusion until a generator-disjoint evaluation
shows incremental value, acceptable latency, and a lawful deployment path.

Recent primary research supports complementary signals and robustness testing rather than a single
universal artifact rule:

- [Community Forensics, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Park_Community_Forensics_Using_Thousands_of_Generators_to_Train_Fake_Image_Detectors_CVPR_2025_paper.html)
- [CO-SPY, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Kim_CO-SPY_Combining_Semantic_and_Pixel_Features_to_Detect_Synthetic_Images_by_CVPR_2025_paper.html)
- [Forensic Self-Descriptions, CVPR 2025](https://openaccess.thecvf.com/content/CVPR2025/html/Nguyen_Forensic_Self-Descriptions_for_AI-Generated_Image_Detection_CVPR_2025_paper.html)

Research-only or noncommercial repositories may inform experiments and the model tournament, but
their code or weights must not silently enter a commercial API. License boundaries are an engineering
constraint, not a reason to erase useful research from the playbook.

## Clear-result UI contract

The default case view contains only:

1. one **bottom line** with a next action;
2. three clickable lane cards with plain conclusions;
3. the analysis navigation.

The origin lane contains:

1. plain conclusion;
2. one-sentence explanation;
3. next action;
4. three facts: Content Credentials, model-family coverage, robustness;
5. collapsed technical evidence.

Technical evidence contains raw model signals, stability, family labels, calibration state, and
machine-readable reason codes. It explicitly says raw outputs are not percentages or universal
probabilities. The dynamic conclusion uses an atomic status region for assistive technology.

UI guidance references:

- [USWDS alert guidance](https://designsystem.digital.gov/components/alert/)
- [W3C ARIA status messages](https://www.w3.org/WAI/WCAG21/Techniques/aria/ARIA22)
- [WCAG 2.2](https://www.w3.org/WAI/WCAG22/)

## What must still be validated

The code change alone cannot establish accuracy. Before a demo claim, run a labeled corpus containing:

- AI art from several modern generators not used for calibration;
- human digital art and photography hard negatives;
- AI-retouched human images and human-retouched AI images;
- JPEG, WebP, social-media resize, screenshot, blur, sharpening, crop, and color edits;
- source-disjoint real images;
- creator- and generator-disjoint splits;
- the specific art domains shown in the ideathon demo.

Report ROC-AUC, average precision, FPR at 95% TPR, TPR at 1% FPR, abstention, selective accuracy,
confidence intervals, and worst-generator/source performance. A screenshot or a tiny set of handpicked
examples is not a benchmark.

## Non-negotiable product language

- Say **AI-generation indicators**, not “proved AI,” unless trusted provenance confirms it.
- Say **no strong indicators found**, not “human-made.”
- Say **same-work evidence**, not “infringement probability.”
- Say **creator-style resemblance**, not “training-data theft.”
- Preserve the evidence packet, model versions, calibration dataset identifier, and proof receipt.
