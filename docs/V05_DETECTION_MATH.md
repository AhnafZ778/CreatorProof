# CreatorProof v0.5 — detection math and decision semantics

Version: 0.5.0 / `CORROBORATED-EVIDENCE-2026.08.09`

This document describes the code that is actually active in v0.5. None of the values below is a
probability of copyright infringement. Legal infringement depends on facts and law outside an image
detector. The product emits source-scoped visual evidence and customer-policy outcomes.

## 1. Global retrieval signals

For SSCD, the model returns an L2-normalized descriptor. CreatorProof records cosine similarity

`s_sscd = z_q^T z_r`.

For the 64-bit perceptual hash,

`s_phash = max(0, 1 - HammingDistance(h_q, h_r) / 64)`.

SHA-256 equality is a separate exact-byte claim. Any SHA-256 equality is sufficient for
`EXACT_BINARY_COPY`; pHash or SSCD equality is not.

Global retrieval nominates the top K catalog candidates. It does not own the final candidate order.

## 2. Robust local geometry

The active verifier uses OpenCV SIFT when available and ORB as a deterministic fallback. Descriptor
pairs must survive a two-nearest-neighbour ratio test in both directions. Only mutual pairs enter the
geometric fit. A homography is estimated with USAC/MAGSAC where OpenCV exposes it.

The transform is accepted only when all current fail-closed gates pass: minimum mutual matches,
minimum inliers, inlier ratio, two-sided spatial coverage, grid dispersion, symmetric transfer error,
and homography determinant/condition checks.

For accepted geometry, v0.5 records the descriptive geometry quality

`q_geo = .25*q_inliers + .30*q_ratio + .25*q_coverage + .20*q_error`

where

- `q_inliers = clamp(inliers / 60)`;
- `q_ratio = clamp(inlier_ratio)`;
- `q_coverage = clamp(sqrt(candidate_coverage * reference_coverage) / .20)`;
- `q_error = clamp(1 - symmetric_error / .0125)`.

If robust geometry is rejected, `q_geo = 0` and no correspondence annotation is exposed.

## 3. Alignment-conditioned structural evidence

This stage runs only after geometry is validated. The candidate is warped into the reference plane and
all measurements are masked to valid overlap.

### Luminance correlation

Pearson correlation is computed on aligned luminance and mapped from `[-1,1]` to `[0,1]`. Because
correlation removes each image's mean and scale, a global brightness/colour edit is much less damaging
than it is to raw pixel distance.

### Gradient correlation and gradient-magnitude similarity

Sobel gradient magnitudes are computed after a small Gaussian blur. CreatorProof records their aligned
correlation and a gradient-magnitude similarity map

`GMS(x) = (2*g_q(x)*g_r(x) + c) / (g_q(x)^2 + g_r(x)^2 + c)`

with `c = 0.0025` in normalized luminance-gradient units. The masked mean is recorded.

### Local structural similarity

On normalized luminance, Gaussian local means, variances, and covariance are used in the standard
luminance/contrast/structure form

`S(x) = ((2*mu_q*mu_r + C1)*(2*cov_qr + C2)) / ((mu_q^2 + mu_r^2 + C1)*(var_q + var_r + C2))`

with `C1=.01^2` and `C2=.03^2`. Warp borders are eroded before pooling.

### Structure consensus

The available luminance-correlation, gradient-correlation, gradient-magnitude, and local-structure
scores are combined with a geometric mean:

`s_structure = exp(mean(log(max(s_i, 1e-6))))`.

A geometric mean is intentionally less forgiving than a simple average: one weak structural family is
not hidden by one near-perfect family. Colour similarity is reported for explanation but is not a match
gate because recolouring is a normal copy/edit transformation.

## 4. Corroborated copy fusion

The UI's copy evidence index is

`E = .25*s_retrieval + .15*s_phash + .32*q_geo + .28*s_structure`,

where `s_retrieval` is SSCD when available and pHash otherwise. Missing geometry/structure contributes
zero. `E` is a ranking/explanation index, not a calibrated probability.

The actual decision is gated rather than thresholding `E` alone. A non-byte-identical match currently
requires validated geometry plus at least one of these auditable paths:

1. strong aligned structure (`>= .76`) and either SSCD support (`>= .55`) or pHash support (`>= .78`);
2. exceptionally strong structure (`>= .84`) and geometry quality (`>= .72`); or
3. validated geometry plus SSCD `>= .70`.

This is why an SSCD cosine of 0.72 no longer vetoes overwhelming local/structural evidence. Conversely,
a high SSCD or pHash value without local corroboration can only become `REVIEW_CANDIDATE`, never
`MATCH_FOUND`.

## 5. Verification re-ranking

SSCD's retrieval rank is retained in every Evidence Packet. All retrieved candidates are then pairwise
verified. Exact matches rank first, then corroborated matches, review candidates, and unverified nearest
neighbours; the evidence index breaks ties. The UI shows both retrieval rank and verification rank.

## 6. Cross-content creator-style profile

Style deliberately does not use homography. For creator `c`, normalized work descriptors are averaged
and renormalized to a centroid `p_c`. The query-to-profile evidence is

`s_profile = .65*cos(q,p_c) + .35*median(top3_i cos(q,z_i))`.

The system additionally records median within-profile pairwise cohesion. When at least three creator
profiles exist, it records a catalog-relative z-score

`z_c = (s_profile(c) - mean_c(s_profile)) / std_c(s_profile)`.

Those values remain uncalibrated retrieval evidence. They must not be converted into “artist copied” or
“trained on artist” claims. The active learned provider remains optional CSD; the transparent fallback is
palette/tone/edge-orientation/texture diagnostics.

## 7. Calibration requirement

The numeric gates above are prototype operating points, not universal constants. Production promotion
requires a domain-held-out labeled corpus with transforms, partial crops, collages, screenshots,
re-encoding, AI retouching, related-style hard negatives, repeated patterns, and unrelated negatives.

Run:

`uv run python -m scripts.benchmark_copy_fusion path/to/manifest.json`

Track at minimum recall, precision, false-positive rate, review rate, ROC-AUC of the evidence index,
per-transformation slices, and confidence intervals. A threshold change should be accepted only when it
improves the chosen operating point on held-out data rather than one showcase image.
