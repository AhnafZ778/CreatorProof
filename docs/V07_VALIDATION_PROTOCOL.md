# CreatorProof v0.7 — validation and red-team protocol

Passing unit tests proves that code behaves as specified. It does **not** prove that a forensic
model is accurate. This protocol separates four promotion levels.

| Level | Meaning | Allowed claim |
| --- | --- | --- |
| Runtime | Dependencies load and deterministic checks pass | “The provider is active” |
| Smoke test | Tiny hand-built examples exercise the path | “The demo flow works” |
| Domain calibrated | Held-out, source-disjoint customer-like corpus passes gates | “Measured at this operating point on this domain” |
| Production monitored | Pre-registered evaluation plus drift/appeal monitoring | Only claim metrics with dataset, interval, and date |

## 1. Dataset partitions

Use separate `train`, `calibration`, `validation`, and locked `test` partitions. The final test set
must never select thresholds, model weights, ensemble weights, or UI language.

### Leakage keys

Split by the strongest available unit, not file name:

- generator family and checkpoint;
- prompt/seed lineage;
- source photograph or source artwork;
- creator identity;
- collection/batch/social post;
- transformation lineage;
- reference work identity.

Near-duplicates of one source must remain in one partition. Random file-level splitting is invalid.

## 2. AI-origin evaluation

### Minimum evaluation manifest

```json
{
  "dataset_id": "customer-domain-test-v1",
  "generator_disjoint": true,
  "images": [
    {"path": "real/camera-a/001.jpg", "label": 0, "source": "camera-a"},
    {"path": "fake/unseen-gen/001.png", "label": 1, "generator": "unseen-gen"}
  ]
}
```

Run:

```bash
cd apps/api
uv run python -m scripts.benchmark_synthetic_detection /absolute/path/manifest.json
```

The script refuses to label a run promotion-eligible unless it has at least 100 AI images, 100 real
images, 5 fake-generator groups, 3 real-source groups, and an explicit generator-disjoint marker.
This is still only a floor; production evaluation should be much larger.

### Required test groups

- unseen diffusion and autoregressive generators;
- commercial API outputs when terms permit evaluation;
- photographs, scans, screenshots, digital paintings, vector-like art, anime, typography-heavy
  work, and 3D renders;
- human digital art and heavily edited photography as hard real negatives;
- AI-assisted edits of real media as a separate mixed-origin class;
- JPEG quality 95/75/50/30;
- repeated social-media resize/recompress cycles;
- crop, blur, sharpening, colour shifts, watermark overlays, screenshots, and metadata stripping;
- low-resolution and high-resolution images;
- non-Western/local art and Bangladesh-relevant visual domains.

### Required metrics

- ROC-AUC and average precision;
- FPR at 95% TPR;
- TPR at 1% FPR;
- selective coverage and selective accuracy after abstention;
- abstention rate;
- calibration ECE and Brier score only for accepted calibrated providers;
- group-level performance by generator/source/domain/transform;
- 95% confidence intervals;
- worst-group performance, not only macro average.

Accuracy alone is unacceptable on a balanced toy set, and a high AUC is not enough if the selected
operating point has an intolerable false-positive rate on human digital art.

### Useful public evaluation sources

- [Community Forensics evaluation data](https://github.com/JeongsooP/Community-Forensics)
- [RRDataset](https://github.com/ChunXiaostudy/RRDataset)
- [So-Fake social-media benchmark](https://github.com/hzlsaber/So-Fake)
- [Chameleon/AIDE](https://github.com/shilinyan99/AIDE) — review its data terms before use.
- [Kaggle Shutterstock/DeepMedia competition](https://www.kaggle.com/competitions/detect-ai-vs-human-generated-images)
- [CIFAKE](https://www.kaggle.com/datasets/birdy654/cifake-real-and-ai-generated-synthetic-images)
  for pipeline sanity only. Its 32×32 CIFAR-10 versus Stable Diffusion 1.4 construction is not a
  realistic deployment benchmark.

## 3. Synthetic-score calibration

Collect raw per-provider rows only from the calibration partition:

```json
{
  "dataset_id": "customer-calibration-v1",
  "domain": "digital-art-prepublication",
  "rows": [
    {
      "partition": "calibration",
      "provider": "community-forensics-vit-small-384",
      "model_version": "official-384-checkpoint",
      "score": 0.81,
      "label": 1
    }
  ]
}
```

Fit:

```bash
uv run python -m scripts.calibrate_synthetic_scores scores.json \
  --output models/synthetic-calibration.json --minimum-per-class 25
```

Then evaluate the frozen calibration on validation/test data. Delete or quarantine calibration when
the model hash, preprocessing, target domain, or generator population changes.

## 4. Copy-detection evaluation

### Positive families

- byte-identical copy;
- recompression and resolution changes;
- moderate crop and letterboxing;
- colour grade, contrast, mild denoise/sharpen;
- local retouch or AI touch-up preserving composition;
- partial-region reuse;
- perspective/rotation when applicable;
- text/logo/layout reuse for relevant customer domains.

### Hard-negative families

- same subject, different image;
- same template family, different assets;
- repeated borders, grids, typography, maps, line art, and geometric patterns;
- same movement/genre/palette;
- same creator, genuinely different work;
- generated style imitation with different composition;
- unrelated image that produces an accidental homography.

The key false-positive test is: a different work by the same creator must not become
`MATCH_FOUND` merely because repeated mark-making produces local keypoints.

### Metrics

- retrieval top-1 and recall@5;
- pair verification precision/recall;
- false-positive rate by hard-negative family;
- partial-copy localization precision/coverage where masks exist;
- calibration curve for the evidence index, without calling it a probability;
- confidence intervals and minimum sample count;
- error cases saved with raw metrics and model versions.

Tiny runs are explicitly `SMOKE_TEST_ONLY`. A reasonable pre-pilot floor is at least 200 positives
and 500 hard negatives across five transformation/negative families; production needs more.

## 5. Creator-style evaluation

Style evaluation must be creator-disjoint and content-aware.

### Positive queries

- held-out work by the same creator with different composition;
- different subject and colour palette where the creator's mechanics remain recognizable;
- genuine commissioned/collaborative edge cases labelled separately.

### Negative queries

- same medium or movement, different creator;
- same subject and palette, different creator;
- student/fan imitation and human stylistic influence;
- AI-generated work prompted toward a profile;
- near-copy positives excluded from the style-only subset;
- anonymous/generic style with no valid profile.

### Required profile support

- at least 3 references per creator for UI high-tier eligibility;
- preferably 8–20 diverse works per creator for serious evaluation;
- at least 20 creators in a pilot benchmark;
- at least 19 cross-creator negatives per target profile for a possible smoothed tail of 0.05;
- creator-disjoint test folds for model selection.

### Metrics

- top-1 creator and recall@5;
- verification ROC-AUC and precision-recall AUC;
- false-accept rate at selected true-accept rate;
- equal-error rate as a diagnostic, not the default operating point;
- per-creator and worst-creator performance;
- cross-genre/content-confound slices;
- conformal negative-tail validity and empirical coverage;
- high-tier false-review rate;
- profile-size sensitivity.

## 6. Joint-policy evaluation

Create a factorial suite across origin/copy/style support:

| Case | Origin | Copy | Style | Expected route |
| --- | --- | --- | --- | --- |
| J1 | AI | yes | any | copy/rights review |
| J2 | human/unknown | yes | any | copy/rights review; origin unresolved |
| J3 | AI | no | calibrated high | combined AI + style review |
| J4 | unknown | no | high | style evidence only; no automatic AI claim |
| J5 | AI | no | low | AI-origin review only |
| J6 | low/unavailable | no | low | source-scoped policy pass |

Assertions must verify that style never changes `NO_MATCH_IN_CHECKED_SOURCES` to `MATCH_FOUND`, and
AI-origin never turns resemblance into infringement.

## 7. Provenance and proof tests

### C2PA

- valid manifest, trusted signer, AI action;
- valid manifest, untrusted signer;
- invalid/tampered manifest;
- missing manifest;
- malformed tool output;
- timeout/unavailable binary.

Missing C2PA must always remain inconclusive.

### Merkle log

- append 1, 2, odd, and even tree sizes;
- verify every inclusion path;
- mutate packet hash/root/sibling/side and require failure;
- ignore malformed historical records without accepting them as leaves;
- concurrent appends preserve complete lines and unique indices.

### EAS

- configuration completeness and address/UID validation;
- testnet transaction succeeds;
- receipt status equals 1;
- Attested event yields UID;
- `isAttestationValid(uid)` returns true;
- packet hash matches local packet;
- explorer URL and chain ID are correct;
- no private evidence appears in calldata beyond ABI framing and packet commitment.

## 8. Security and privacy gates

- Reject decompression bombs and over-limit payloads.
- Decode images into a safe RGB representation before model access.
- Never pass user paths through a shell.
- External detector commands are argument arrays with a literal `{image}` placeholder.
- Do not load untrusted pickle checkpoints. Prefer safetensors/TorchScript; pin hashes for any
  explicit legacy exception.
- API keys remain server-side and are never rendered to browser JavaScript.
- Candidate retention is short and configurable.
- Evidence Packet exposes commitments and summaries, not raw private media.
- EAS receives only one `bytes32` commitment.

## 9. Hackathon acceptance checklist

- [ ] `ruff check` and `ruff format --check` pass.
- [ ] Backend unit/integration tests pass.
- [ ] TypeScript check and production build pass.
- [ ] Health endpoint identifies v0.7 and every provider state.
- [ ] One near-copy retrieves the correct work and verifies structure.
- [ ] One hard negative emits no correspondence regions.
- [ ] One style-only positive leaves copy negative.
- [ ] AI-origin view shows each detector and transform stability.
- [ ] An unstable synthetic detector visibly abstains.
- [ ] A tiny benchmark says `SMOKE_TEST_ONLY`, never 100%-ready.
- [ ] C2PA absence says unknown, not human.
- [ ] Local proof verifies and says not blockchain.
- [ ] Optional EAS proof links to a real testnet transaction.
- [ ] Mobile and desktop navigation expose all six analysis modes.
- [ ] Every score is labelled evidence/index, not infringement probability.

## 10. Honest release statement

The acceptable release statement is:

> CreatorProof v0.7 is a functioning, research-backed prototype with auditable three-lane evidence,
> transformation-aware AI-origin abstention, catalog-conditional style calibration, robust copy
> corroboration, C2PA inspection, and verifiable proof receipts. Accuracy claims remain limited to
> the named held-out dataset and operating point.

Do not replace that with “perfect,” “bulletproof,” or “100% accurate.”
