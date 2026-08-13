# CreatorProof v0.7 — active detection and proof mathematics

This is the implementation contract for v0.7. Symbols describe the actual code paths; none of the
scores below is a legal-infringement probability.

## 1. Shared notation

Let candidate image be (x), registered work (r_j), creator profile (c), origin detector (m),
and robustness transform (t). All similarities are clipped to ([0,1]) when entering fusion.

The logit and sigmoid functions are:

\[
\operatorname{logit}(p)=\log\frac{p}{1-p},\qquad
\sigma(z)=\frac{1}{1+e^{-z}}.
\]

Inputs are clipped to ([10^{-6},1-10^{-6}]) before a logit.

## 2. AI-origin lane

### 2.1 Robustness views

Each active detector sees the original image and four non-adversarial probes:

\[
T=\{\text{original},\text{JPEG95},\text{JPEG75},
\text{resize}_{0.72}\!\rightarrow\!\text{restore},\text{blur}_{0.55}\}.
\]

The quality weights in the current build are:

\[
w_t=\{1.00,0.92,0.76,0.78,0.72\}.
\]

These probes do not “vote five times.” They estimate whether one detector is stable under common
delivery transformations.

### 2.2 Per-model calibration

For raw detector score (s_{m,t}), held-out Platt parameters (a_m,b_m) are applied only when:

- provider name matches;
- model version matches when recorded;
- total calibration samples meet the configured minimum;
- both classes meet the configured per-class minimum;
- (a_m>0) and all parameters are finite.

Then:

\[
\tilde{s}_{m,t}=\sigma\!\left(a_m\operatorname{logit}(s_{m,t})+b_m\right).
\]

Otherwise (	ilde{s}_{m,t}=s_{m,t}), and the score is labelled raw/non-probabilistic.

### 2.3 Transform aggregation and stability

The detector aggregate is a weighted mean in log-odds space:

\[
q_m=\sigma\left(
\frac{\sum_{t\in T} w_t\operatorname{logit}(\tilde{s}_{m,t})}
{\sum_{t\in T}w_t}
\right).
\]

Let (sigma_m) be the standard deviation of scores over available transforms. The bounded stability
index is:

\[
u_m=\max\left(0,1-\frac{\sigma_m}{\tau_{\mathrm{view}}}\right),
\]

where (	au_{\mathrm{view}}=0.18) by default.

### 2.4 Multi-model fusion

Each member receives reliability

\[
\rho_m=c_m(0.45+0.55u_m),
\]

where (c_m=1.0) for an accepted calibrated output and (c_m=0.78) otherwise. The ensemble index is:

\[
Q=\sigma\left(
\frac{\sum_m\rho_m\operatorname{logit}(q_m)}{\sum_m\rho_m}
\right).
\]

Model disagreement is (d=\operatorname{std}_m(q_m)); overall transform stability is
(U=\operatorname{mean}_m(u_m)).

### 2.5 Abstention and decision gates

Provenance is evaluated before model scores.

1. Trusted valid C2PA AI assertion → `AI_PROVENANCE_CONFIRMED`.
2. Valid AI assertion from an untrusted signer → review, not confirmation.
3. No detector → unavailable.
4. Short side below 128 px → abstain.
5. (U<0.35) → abstain for transform instability.
6. (d\ge0.22) → abstain for model disagreement.
7. (Q\ge0.78), with 2+ models, or a single model at least (0.85) → `LIKELY_AI_GENERATED`.
8. (Q\ge0.58) → review range.
9. (Q\le0.42) → no AI-origin evidence detected, explicitly not proof of human origin.
10. Otherwise → inconclusive.

Thresholds are prototype defaults. Deployment values must be selected on generator-, source-, and
transformation-disjoint validation data.

## 3. Same-work copy lane

### 3.1 Retrieval

SSCD embeddings are L2-normalized. Global similarity is cosine:

\[
s_{\mathrm{SSCD}}(x,r_j)=f(x)^\top f(r_j).
\]

This ranks candidate references. It does not itself establish copying.

pHash support is:

\[
s_{\mathrm{pHash}}=\max\left(0,1-\frac{d_H}{64}\right),
\]

where (d_H) is 64-bit Hamming distance.

### 3.2 Robust geometry

Local descriptors are mutually ratio-filtered before USAC/MAGSAC estimates homography (H).
Validation includes:

- minimum mutual match and inlier counts;
- inlier ratio;
- query and reference spatial coverage;
- inlier dispersion;
- forward and symmetric transfer error;
- projected-corner/homography sanity.

For normalized correspondence (p_i\leftrightarrow p'_i), symmetric transfer error is conceptually:

\[
e_{\mathrm{sym}}=\operatorname{median}_i\left(
\lVert p'_i-\pi(Hp_i)\rVert_2+
\lVert p_i-\pi(H^{-1}p'_i)\rVert_2
\right).
\]

The geometry quality displayed by fusion is:

\[
G=0.25I+0.30R+0.25C+0.20E,
\]

where:

\[
I=\min(n_{\mathrm{inlier}}/60,1),\quad
R=\operatorname{clip}(r_{\mathrm{inlier}}),
\]

\[
C=\operatorname{clip}\left(\frac{\sqrt{c_xc_r}}{0.20}\right),\quad
E=\operatorname{clip}\left(1-\frac{e_{\mathrm{sym}}}{0.0125}\right).
\]

### 3.3 Alignment-conditioned structure

Structural comparison runs only when geometry is valid. The reference is warped by (H^{-1}) into
candidate coordinates and scored over valid overlap. The verifier exposes luminance correlation,
gradient correlation, gradient-magnitude similarity, structural similarity, colour similarity, and
overlap. Its conservative structure consensus (S) is the aligned verifier's bounded aggregation;
colour is descriptive and cannot veto a retouched copy.

### 3.4 Copy fusion

The descriptive copy index is:

\[
C_{\mathrm{copy}}=operatorname{clip}\left(
0.25s_{\mathrm{retrieval}}+0.15s_{\mathrm{pHash}}+0.32G+0.28S
\right).
\]

This index orders evidence. The match is controlled by explicit gates, not by the index alone.

A non-byte-identical match requires one of:

\[
\text{geometry}\land S\ge0.76\land
(s_{\mathrm{SSCD}}\ge0.55\lor s_{\mathrm{pHash}}\ge0.78),
\]

or an exceptionally strong structural path:

\[
\text{geometry}\land S\ge0.84\land G\ge0.72,
\]

or a very-strong global path that still requires structure:

\[
\text{geometry}\land s_{\mathrm{SSCD}}\ge0.86\land G\ge0.72\land S\ge0.62.
\]

The key invariant is:

\[
\neg\text{aligned structure}\implies\neg\text{non-identical MATCH\_FOUND}.
\]

Exact SHA-256 equality remains an immediate binary-copy result.

## 4. Creator-style lane

### 4.1 Learned creator profile

Let (z_x) be the normalized CSD query descriptor and (z_i) registered style descriptors.
For creator (c) with reference indices (I_c), raw pool cosine is:

\[
r_c=\frac{1}{|I_c|}\sum_{i\in I_c} z_x^\top z_i.
\]

### 4.2 CSD+-style CSLS correction

Let (r_x) be the mean similarity of the query to its (k) nearest catalog references, and (r_i)
the mean similarity of anchor (i) to its (k) nearest *other* anchors. Profile rank score is:

\[
\operatorname{CSLS}(x,c)=2r_c-r_x-\frac{1}{|I_c|}\sum_{i\in I_c}r_i.
\]

CSLS is used for ranking, not as a probability or direct fusion component.

### 4.3 Corroborating mechanics

The transparent mark-making score is:

\[
M=0.10P+0.15T+0.375O+0.375X,
\]

where (P) is palette similarity, (T) tone, (O) stroke/edge-orientation, and (X) texture.

Bidirectional tile consistency uses medians so one spectacular tile cannot dominate:

\[
B=0.5\operatorname{median}(b_{x\rightarrow r})+
0.5\operatorname{median}(b_{r\rightarrow x}).
\]

Content similarity (K) is measured separately with SSCD. With learned style cosine (L), the
style-minus-content gap is:

\[
\Delta=L-K,
\]

and the bounded separation support is:

\[
D=\operatorname{clip}\left(\frac{\Delta+0.05}{0.45}\right).
\]

### 4.4 Style evidence index

With all components available:

\[
C_{\mathrm{style}}=0.50L+0.25M+0.15B+0.10D.
\]

Weights are renormalized when a diagnostic component is unavailable. If the learned style model is
unavailable, the lane is `DIAGNOSTIC` and cannot attribute a creator.

### 4.5 Catalog-conditional conformal control

For target profile (c), leave-one-out within-creator reference scores form positive calibration
set (P_c). Every work from other creator profiles scored against (c) forms negative set (N_c).

For query raw profile score (L), the smoothed cross-creator tail is:

\[
p_{\mathrm{neg}}=
\frac{1+\sum_{n\in N_c}\mathbf{1}[n\ge L]}{|N_c|+1}.
\]

Positive support percentile is:

\[
u_{\mathrm{pos}}=
\frac{1+\sum_{p\in P_c}\mathbf{1}[p\le L]}{|P_c|+1}.
\]

This is catalog-conditional empirical control, not a universal p-value about authorship.

`HIGH` requires, among other corroboration gates:

- learned provider active;
- evidence index at least 0.74;
- at least 3 independent support families;
- at least 3 works in the target profile;
- at least 3 creator profiles and 19 cross-creator negatives;
- positive discrimination gap;
- (p_{\mathrm{neg}}\le0.10);
- (u_{\mathrm{pos}}\ge0.25).

`VERY_HIGH` additionally requires index at least 0.84,
(p_{\mathrm{neg}}\le0.05), (u_{\mathrm{pos}}\ge0.50), and no strong content confound.

Why 19 negatives? With smoothed conformal counting, the minimum possible tail is
(1/(19+1)=0.05). A smaller cohort cannot honestly claim the 0.05 tier.

## 5. Joint triage

Define binary support indicators (A) for strong AI origin, (C) for verified same-work copy, and
(Y) for calibrated high/very-high style resemblance.

\[
J(A,C,Y)=
\begin{cases}
\text{AI-assisted copy evidence}, & A\land C\\
\text{copy evidence; origin unresolved}, & \neg A\land C\\
\text{AI + creator-style review}, & A\land\neg C\land Y\\
\text{style resemblance; origin unresolved}, & \neg A\land\neg C\land Y\\
\text{AI-origin review only}, & A\land\neg C\land\neg Y\\
\text{no joint signal}, & \text{otherwise.}
\end{cases}
\]

This is transparent policy logic. It is not trained on legal outcomes.

## 6. Canonical Evidence Packet commitment

Let (P\setminus\text{proof}) be the Evidence Packet without its proof object. Canonical JSON uses
sorted keys, compact separators, ASCII escaping, and UTF-8 encoding:

\[
h_P=\operatorname{SHA256}(\operatorname{CanonicalJSON}(P\setminus\text{proof})).
\]

Only (h_P) is anchored.

### 6.1 Local transparency log

Merkle leaves and nodes use RFC 6962-style domain separation:

\[
h_{\mathrm{leaf}}=\operatorname{SHA256}(0x00\parallel h_P),
\]

\[
h_{\mathrm{node}}=\operatorname{SHA256}(0x01\parallel h_L\parallel h_R).
\]

The receipt contains tree size, leaf index, root, sibling path, and local verification result. It is
cryptographic transparency, not a blockchain transaction.

### 6.2 Public EAS attestation

The configured EAS schema is exactly:

```text
bytes32 packetHash
```

The transaction attests ABI-encoded (h_P), records the network chain ID, transaction hash,
attestation UID, block number, and calls `isAttestationValid(uid)` after mining. No image or private
evidence is placed on-chain.

## 7. Calibration boundaries

Never compare raw values across model versions as though the scale stayed fixed. A threshold is a
tuple:

\[
(\text{model hash},\text{preprocessing},\text{domain},\text{transform policy},\text{dataset version},
\text{operating point}).
\]

Any change to that tuple invalidates the corresponding calibration until re-evaluated.
