# Evidence Microscope

The Evidence Microscope is CreatorProof's interactive explanation layer. It is intentionally downstream of detection: visualization data may explain evidence, but it must never alter `match_status`, `policy_action`, or `rights_path`.

## Data flow

```text
candidate
  |-> COPY LANE: SSCD/pHash -> nearest work -> ORB + USAC/MAGSAC -> verified regions or none
  |
  `-> STYLE LANE: style embedding -> creator prototypes -> nearest creator/exemplar
                      `-> palette/tone/stroke/texture cross-content diagnostics

copy evidence + style evidence -> Evidence Packet -> React/SVG microscope
```

The current provider stores at most 64 validated local correspondences per candidate in the Evidence Packet. The browser displays at most 40 at one time to keep the diagram legible. A homography that merely *fits* is not enough to produce annotations.

## Contract

Every candidate match may contain `visualization` with:

- `schema`: currently `creatorproof.visual_evidence.v1`.
- `coordinate_space`: `NORMALIZED_IMAGE_0_1`; coordinates survive responsive resizing.
- `query_size` and `reference_size`: original width/height.
- `correspondences`: paired query/reference coordinates, raw ORB descriptor distance, transfer error,
  optional support-patch id, and evidence type.
- `regions`: compact paired support envelopes derived from locally dense verified inliers. These are
  explicitly evidence envelopes, not semantic segmentation masks or claims that every enclosed pixel
  is shared.
- `homography_query_to_reference`: the OpenCV 3x3 transform in original pixel coordinates only after validation (or a safe identity transform for an exact byte match).
- `display_notes`: interpretation guardrails shown by clients.

For byte-identical inputs, the evidence service adds a full-frame `EXACT_BINARY_MATCH` region. If geometry cannot be estimated but identical media dimensions are known, the visual transform may safely fall back to identity because the exact SHA-256 comparison is already true.

## Browser modes in v0.4

### Overview

Shows the candidate beside the copy-nearest registered reference and two explicit lane cards. The
copy card reports SSCD/pHash retrieval plus geometry state. The style card reports the independently
ranked creator profile, number of registered profile works, and uncalibrated prototype similarity.
The two nearest references may be different.

### Copy localization

This is the only mode that draws geometric annotations. Verified support patches are shown when
geometry passes. Local ORB feature pairs are an advanced opt-in layer; the UI explains that a pair
means a local descriptor match that also obeyed the robust global transform, not semantic object
recognition. Hovering a pair exposes descriptor distance and transfer error. If geometry rejects,
the view displays the two images with **zero** regions/lines and says why.

### Style signature

This mode switches the right image to the style-nearest exemplar from the highest-ranked creator
profile. It shows the profile score/provider/sample count separately from transparent low-level
palette, tone, edge-direction, and texture diagnostics. When learned CSD is active, the CSD prototype
score and diagnostic factor bars are deliberately different measurements; the bars are not presented
as an explanation of every latent CSD dimension.

### Cross-content style map

This replaces the old geometry-aligned overlay/difference modes for style inspection. Each image is
divided into 4x4 tiles. A tile searches all tiles in the other image for its nearest transparent style
signature, so spatial positions do not need to align. Selecting a tile shows the best partner tile and
factor values. No geometric line is drawn and no pixel-difference claim is made.

The removed overlay/difference modes remain a valid *copy-forensics* concept for future dedicated
tools, but they are not appropriate evidence for two different compositions being compared for
creator style.

## Media/privacy behavior

The scan candidate preview is a browser-local object URL and is not embedded into the Evidence Packet; with zero-retention enabled, the backend deletes its temporary candidate object after processing. Registered references are different: they are intentionally retained as catalog works. The UI can therefore fetch the selected reference through `/v1/works/{work_id}/media` via the server-side authenticated proxy. This fixes the old same-browser-registration limitation while keeping the development API key out of browser JavaScript.

## Promotion path

The visualization schema is provider-neutral. A learned local matcher can later emit the same normalized correspondence/region structure without rewriting the frontend. Likely promotion experiments include ALIKED/LightGlue, XFeat, LoMa, and RoMa-family candidates subject to the repository/model license and CreatorProof benchmark gates documented elsewhere in this handoff.

For extremely large reference art, a later frontend provider can combine OpenSeadragon with an annotation layer for tiled deep zoom and synchronized viewport navigation. That is an ergonomics/scale upgrade, not a requirement for the hackathon prototype.
