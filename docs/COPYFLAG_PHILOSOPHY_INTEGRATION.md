# CopyFlag philosophy integration

This note records what is publicly visible about CopyFlag, the 2026 Microsoft
Imagine Cup World Champion, and the product principles CreatorProof is adopting.
It does not claim access to CopyFlag's private code, data, model weights, or
operational metrics.

## Publicly verified project

Microsoft announced CopyFlag as the 2026 World Champion at Microsoft Build. It
was built by Patrick Brown, a University of Oxford student. Microsoft describes
it as an Azure-powered platform that detects copied and AI-modified content on
the internet, helps creators identify infringement, and automates takedowns.

- [Microsoft World Champion announcement](https://techcommunity.microsoft.com/blog/StudentDeveloperBlog/announcing-the-2026-imagine-cup-world-champion/4524686)
- [Official Imagine Cup team page](https://imaginecup.microsoft.com/en-us/Team/60d55d08-4acf-4a5d-a50d-4836169f102e)
- [Microsoft founder profile](https://www.linkedin.com/posts/microsoft-imagine-cup_protecting-creative-work-starts-with-activity-7452769374584721408--cwk)

CopyFlag's public product pages describe a post-publication protection workflow:

1. Creators upload designs to a protected catalogue.
2. The service searches marketplaces such as Etsy, Amazon, Redbubble, and Temu.
3. It finds exact, edited, cropped, recoloured, remixed, AI-modified, and
   cross-product uses.
4. It packages visual comparisons, listing URLs, timestamps, screenshots, and a
   ready-to-send DMCA notice.
5. It tracks sellers across platforms, measures visual reuse, identifies repeat
   offenders, predicts relisting, and prioritises threats.

Sources: [CopyFlag](https://www.copyflag.com/), [Creators](https://www.copyflag.com/creators),
[Why CopyFlag](https://www.copyflag.com/why-copyflag), and [AI copyright protection](https://www.copyflag.com/ai-copyright-protection).

CopyFlag also publicly describes an intelligence pipeline of vector embeddings
(CLIP/DINOv2), perceptual hashing, transform-resilient matching, style-transfer
and diffusion-artifact analysis, five parallel detection channels, feedback
loops, uncertainty bands, weighted scoring with history, reoffense prediction,
and enforcement generation. These are public product claims; the exact model
composition, thresholds, training data, and evaluation results are not public.

## Principles adopted by CreatorProof

### Detection must end in an accountable action

CreatorProof now labels every evidence packet with a `protection` posture. The
posture connects the measured result to the next human or policy action while
preserving the existing separation between evidence and legal conclusions.

The product flow is:

```text
detect → corroborate → explain uncertainty → recommend an action → preserve proof
```

### Use several signals for adversarial transformations

CreatorProof already combines exact identity, pHash, SSCD retrieval over
overlapping regions, SIFT/ORB geometry, MAGSAC homography, aligned structure,
Community Forensics, Sightengine, OCR, C2PA, and optional CSD/GRIP signals. A
single similarity score cannot establish copying, so the policy still requires
corroboration before a MATCH.

### Treat uncertainty as product data

Coverage, provider availability, calibration state, fallbacks, evidence quality,
and limitations stay in the packet. Missing evidence remains unknown. A vendor
score or raw detector output is never rendered as a probability without an
authorized calibration file.

### Move from one-shot review toward protection over time

The current product is a pre-publication scan. It does not claim to crawl
marketplaces or identify sellers. The next protection layer should use durable
scan, review, and outcome history to surface repeated candidate hashes, repeated
matched works, unresolved cases, and recurring origin signals. Any future actor
identity must be based on a verified source identifier; image similarity alone
must never invent a person or seller.

## Boundary between the products

CopyFlag is primarily post-publication monitoring and enforcement. CreatorProof is
primarily pre-publication rights, origin, and creator-profile review with a
tamper-evident receipt. The two workflows can complement each other:

- CreatorProof can clear or hold an asset before release.
- A future monitoring connector can feed verified marketplace observations back
  into CreatorProof as a new evidence source.
- CopyFlag-style enforcement should remain an explicit, user-approved action;
  CreatorProof must not send takedowns automatically from a model score.

## Safe implementation sequence

1. **Now:** expose the protection posture in every packet and UI review flow.
2. **Next:** add a tenant-scoped protection overview from existing scan and review
   history: repeat candidate fingerprints, repeated matched works, open-case age,
   and recommended review priority.
3. **Then:** add opt-in marketplace connectors with source URL, timestamp,
   seller/platform identifier, retrieval method, and screenshot hash as required
   evidence fields.
4. **After that:** add outcome feedback (confirmed copy, false positive,
   licensed use, takedown accepted, takedown rejected) and evaluate whether it
   supports a calibrated priority model.

No step should turn style resemblance, AI-origin evidence, or an unverified
marketplace observation into an infringement finding.

