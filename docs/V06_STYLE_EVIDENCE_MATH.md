# CreatorProof v0.6 style-evidence math

Build: `0.6.0 / CSD-PLUS-STYLE-EVIDENCE-2026.08.09`

## 1. The bug this revision fixes

Copy evidence and style resemblance answer different questions. A different composition can have no
valid homography and a low SSCD copy score while strongly resembling a creator's mark-making. v0.5.1
displayed the copy index as the dominant case number even when the independent style lane returned a much
higher score. v0.6 gives each lane its own decision card and forbids style from manufacturing a copy match.

The reported example illustrates the distinction:

- copy evidence index: about `0.64`;
- raw CSD profile similarity: about `0.819`;
- transparent style mechanics: strong edge-direction and texture agreement;
- SSCD content/copy similarity: much lower than the style score.

That is a plausible **cross-content style-review** pattern. It is not a failed copy detector and is not a
legal conclusion.

## 2. Creator anchor pools

All registered works with the same normalized claimant form a creator pool (A). For a query embedding
(x), the raw pool score is

\[
s(x,A)=\frac{1}{|A|}\sum_{a\in A}\cos(x,a).
\]

This replaces the v0.5 ranking dependence on a single normalized centroid. The legacy centroid/top-member
score remains in the packet only for client compatibility and is not the v0.6 ranking score.

## 3. CSD+ local-density correction

Raw CSD cosine is not an absolute calibrated style probability. The 2026 CSD+ preprint documents hubness
and shared-tradition failures and recommends a corpus-aware CSLS readout. CreatorProof implements its
pool form:

\[
r_k(x)=\frac{1}{k}\sum_{y\in N_k(x)}\langle x,y\rangle
\]

\[
\operatorname{CSLS}(x,A)=2s(x,A)-r_k(x)-\frac{1}{|A|}\sum_{a\in A}r_k(a).
\]

The default is (k=15), reduced automatically for small catalogs. Reference self-similarity is excluded
from anchor density. CSLS is active only when the learned CSD provider is active and the catalog has at
least two profiles and three total anchors. It is a **ranking score**, not a percentage.

Primary source: [CSD+ preprint](https://arxiv.org/abs/2605.09030). This is a July 2026 arXiv preprint, not a
peer-reviewed production guarantee.

## 4. Catalog discrimination diagnostic

For every creator, each anchor is scored against its own pool with self excluded. The median of those
leave-one-out scores is (w_A). For each competing creator pool (B), the median cross-pool score is
computed; the strongest competitor is (c_A). The catalog discrimination gap is

\[
g_A=w_A-\max_{B\ne A}c_{A,B}.
\]

- (g_A>0): raw cosine is at least median-order-consistent in this catalog.
- (g_A\le 0): raw cosine is inverted against a catalog neighbour; show the warning and rely on CSLS
  ranking rather than claiming an absolute raw-cosine interpretation.
- `null`: the catalog/profile is too small to diagnose.

## 5. SSCD content-confound control

SSCD remains the copy/content descriptor. For a creator pool, CreatorProof computes

\[
c(x,A)=\frac{1}{|A|}\sum_{a\in A}\cos_{SSCD}(x,a)
\]

and reports the style-content gap

\[
\Delta_{style-content}=s(x,A)-c(x,A).
\]

This is not a veto. A large positive gap is useful evidence that the CSD resemblance is not merely the
same object/layout. High style and high content is labelled `STYLE_AND_CONTENT_CONFOUNDED` and should be
read with the copy lane. If SSCD is unavailable, content control is explicitly unavailable.

## 6. Transparent style mechanics

The explainable descriptor reports palette (p), tone (t), edge/stroke orientation (o), and LBP
texture (u). Palette receives the least weight because it is easy to share accidentally:

\[
m=0.10p+0.15t+0.375o+0.375u.
\]

The 4×4 style map performs all-to-all tile comparison in both directions. Whole-image tile consistency is
the mean of the two directional medians, preventing one spectacular tile from dominating the decision.
Tiles are diagnostic style neighborhoods, not copied regions.

## 7. Corroborated style evidence index

When learned CSD and SSCD content control are present, available components use these nominal weights:

| Component | Weight | Meaning |
| --- | ---: | --- |
| Raw learned CSD pool similarity | 0.50 | Style-specific embedding evidence |
| Style mechanics | 0.25 | Mark-making, texture, tone, palette |
| Bidirectional tile consistency | 0.15 | Cross-content local style stability |
| Style/content separation support | 0.10 | Whether style exceeds copy/content similarity |

Missing components are removed and remaining weights are renormalized. Separation support is a clipped
prototype mapping of the style-content gap, not a learned probability. When CSD is unavailable, the
diagnostic mechanics/map can be shown but the tier is forced to `DIAGNOSTIC` and cannot trigger policy
review.

Default prototype operating points are visible in `.env.example`:

- review index: `0.58`;
- high index: `0.74` with at least two independent supports and learned CSD active;
- very high index: `0.84`, at least three supports, at least three creator works, and positive
  discrimination gap.

These values are engineering defaults, not universal scientific thresholds. Calibrate them on held-out,
creator-disjoint customer data.

## 8. Policy semantics

The style lane never changes copy `match_status`:

- no geometry/source support remains `NO_MATCH_IN_CHECKED_SOURCES` or `INCONCLUSIVE`;
- learned `HIGH`/`REVIEW` style evidence can change `PASS_BY_POLICY` to `REVIEW`;
- it adds `STYLE_REVIEW_IS_NOT_COPY_OR_INFRINGEMENT_FINDING` to the reason codes;
- diagnostic fallback never escalates policy.

This is the correct B2B behavior: surface risk for a human workflow without pretending a model decided
copyright law.

## 9. Calibration contract

Use different-content positives and difficult negatives from nearby movements/genres. Split by creator,
not random image, to prevent identity leakage. Report raw and CSLS top-1, recall@k, pair ROC-AUC,
dataset-specific EER, per-creator discrimination gaps, false-positive rate at the chosen review threshold,
and bootstrap confidence intervals before production promotion.

`scripts.benchmark_style_retrieval` implements the first measurable gate. It intentionally does not write
new production thresholds automatically.

