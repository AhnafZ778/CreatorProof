# CreatorProof v0.9.0 — packaging execution and audit report

Date: 2026-08-09  
Build signature: `PLAIN-SCORE-WATERMARK-2026.08.09`  
Promotion in this packaging workspace: **SOURCE_VERIFIED / TARGET-MACHINE MODEL ACTIVATION AND
REAL-CORPUS VALIDATION REQUIRED**

## 1. Outcome

v0.9 fixes the remaining no-match origin contradiction and restores understandable scoring without
turning a raw detector response into a fake probability.

Implemented:

- AI-origin output remains independent of registered-work retrieval;
- a no-match catalog result cannot suppress positive, uncertain, or unavailable origin evidence;
- unresolved origin converts an otherwise catalog-scoped `PASS_BY_POLICY` into product `REVIEW`;
- local visible-label OCR covers the full image and overlapping corners;
- both sparse and block OCR layouts run, with handling for the common `AI`/`Al` recognition error;
- explicit AI-use text is localized and shown on the candidate image;
- missing, unavailable, or failed OCR remains neutral;
- visible text can force review but never becomes trusted provenance;
- a two-part 0–100 scorecard shows **AI signal** and **Evidence quality**;
- both scores expose their factors and explicitly state that they are not probabilities;
- the normal UI uses four plain question views, larger type, clearer colors, and progressive
  disclosure;
- provider ledgers, raw values, machine codes, and forensic diagnostics stay available under
  advanced details;
- the target-machine prompt now includes a real watermark test matrix, no-match E2E cases, model
  tournament, calibration, accessibility, and honest promotion gates.

This release reduces unsupported negative certainty. It does not establish universal AI-image
detection or legal infringement.

## 2. Packaging environment

| Component | Observed version |
| --- | --- |
| Linux kernel | 6.18.35 x86_64 |
| Python | 3.12.13 |
| uv | 0.11.33 |
| Node.js | 24.14.0 |
| npm | 11.9.0 |
| Git | 2.51.1 |
| Git LFS | 3.4.1 |
| Tesseract | 5.3.4 |
| Next.js | 16.3.0 |
| CreatorProof API/Web | 0.9.0 |

## 3. Checks actually completed

Backend:

```bash
UV_CACHE_DIR=/tmp/creatorproof-v09-uv-cache uv run ruff check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-v09-uv-cache uv run ruff format --check app tests scripts
UV_CACHE_DIR=/tmp/creatorproof-v09-uv-cache uv run pytest -q
```

Result:

- Ruff lint: **PASS**;
- Ruff format: **PASS**, 71 files checked;
- Pytest: **44/44 PASS**;
- non-failing warning: the installed FastAPI/Starlette TestClient exposes an upstream `httpx`
  compatibility deprecation.

Frontend:

```bash
npm run typecheck
npm run build
```

Result:

- TypeScript: **PASS**;
- Next.js production build: **PASS**;
- all expected static and dynamic routes generated;
- non-failing warning: the host npm `http-proxy` setting is deprecated for a future npm major.

## 4. Real visible-label verification

The test suite includes both deterministic OCR-output tests and a real Tesseract test. The real test
draws a high-contrast `AI GENERATED` label, calls the installed Tesseract binary through the actual
provider, and requires a localized `VISIBLE_AI_MARKER_FOUND` result.

The initial real test exposed a genuine failure: sparse-text mode returned no useful text and block
mode read `AI` as `Al`. The implementation was corrected to run both layouts and tolerate that
specific OCR confusion only in the explicit `AI generated` phrase. The real test then passed.

Covered behaviors:

- explicit AI label found and normalized box emitted;
- unrelated ordinary text remains negative for the marker check;
- unavailable OCR is not reported as “no label”;
- real Tesseract inference detects the high-contrast label;
- a visible label routes origin review with no learned detector;
- missing label is neutral in origin fusion.

This is a smoke/regression test, not a watermark-recall benchmark. Small, translucent, rotated,
multilingual, logo-only, and post-processed watermarks still require the target-machine test matrix.

## 5. No-match and policy verification

Regression tests now prove:

- `NO_MATCH_IN_CHECKED_SOURCES` plus a visible AI label reports **AI origin needs review**;
- quiet models do not produce a human-origin claim;
- unavailable or unresolved AI-origin evidence changes source-scoped catalog pass to `REVIEW`;
- that review carries `AI_ORIGIN_REVIEW_IS_NOT_INFRINGEMENT_FINDING`;
- style evidence still cannot manufacture a copy match;
- a valid licensed same-work policy is not overwritten merely by style review.

The case summary and API policy therefore agree. “No stored-work match” remains visible as a separate
fact but cannot clear the independent origin lane.

## 6. Scorecard semantics

The restored values are:

- **AI signal /100** — the strongest available reaction across learned-family fusion, visible AI
  label, and signed source evidence, with a small corroboration bonus;
- **Evidence quality /100** — coverage, held-out calibration, delivery stability, OCR confidence
  capped for forgeability, and signer trust.

Missing inputs are omitted rather than counted against AI origin. A high signal with low evidence
quality stays in review. The response includes factor rows for model checks, visible label, and signed
source information. The raw calibrated-domain model score remains hidden unless all required
families have accepted provider/version-matched calibration.

## 7. UI verification state

Source/build checks verify the redesigned UI compiles. It now provides:

- a bottom line and next action first;
- three large lane cards;
- four primary analysis views;
- larger responsive typography and controls;
- plain English labels;
- the two-part origin scorecard;
- visible-label image highlighting;
- secondary structure/style-map controls inside their parent lane;
- collapsed advanced system and model detail.

No live browser observation is claimed from this packaging workspace. Desktop, 390px mobile,
keyboard, 200% zoom, accessibility-tree, long-content, and five-second comprehension checks remain
mandatory on the target machine.

## 8. Model/provider state in this archive

Weights, external repositories, credentials, user images, and benchmark corpora are deliberately
excluded.

| Provider | Observed packaged state | Target-machine action |
| --- | --- | --- |
| SSCD work retrieval | Inactive; model file missing | Fetch model and run `scripts.check_ai` |
| CSD learned style | Inactive; transparent diagnostic fallback active | Fetch CSD runtime and require learned check |
| Community Forensics | Inactive; safetensors absent | Run fetch script and `scripts.check_synthetic_ai` |
| GRIP CLIPDet | Clean external adapter only | Clone official Git-LFS repo in isolated environment |
| Visible AI labels | **Active**, Tesseract 5.3.4 | Run real watermark matrix on target images |
| C2PA | Provider boundary present | Install official `c2patool` and trust material |
| Local Merkle receipt | Implemented | Verify a generated receipt at runtime |
| EAS public anchor | Optional boundary, not configured | Use operator-provided testnet values only |
| OpenRouter explainer | Optional and blank | Not required for detection |

Provider checks correctly reported no learned origin detector, no origin calibration file, no SSCD
model, and no CSD checkout. No accuracy number is reported from this workspace.

## 9. Research conclusions applied

Recent primary research reinforces the v0.9 design rather than supporting one universal detector:

- generator-aware prototypes and image-adaptive prompting target unseen-generator generalization;
- the NTIRE robustness challenge centers realistic resizing, compression, and distribution shifts;
- Difference-in-Difference offers reconstruction behavior as a potentially complementary family;
- QuAD argues for quality-aware aggregation across near-duplicates;
- C2PA supplies signed provenance when present, while absence remains inconclusive.

These are model-tournament candidates or architecture inputs. They were not silently embedded or
reported active. `docs/V09_ORIGIN_SCORE_AND_PRODUCT_UI.md` records the evaluation route and license
boundaries.

## 10. Remaining blockers

1. Activate and hash-pin at least Community Forensics and GRIP as independent learned families.
2. Build authorized source-lineage- and generator-disjoint calibration, validation, and locked-test
   partitions for the ideathon domain.
3. Run the full visible watermark matrix, including PaddleOCR as an optional challenger.
4. Run the ten real E2E cases in `MASTER_EXECUTION_PROMPT_v0.9.md`.
5. Complete desktop/mobile/accessibility UI observation.
6. Rehearse and record the target-machine demo; do not rely on packaging tests as an accuracy claim.

## 11. Correct release statement

CreatorProof v0.9 is a source-verified prototype that keeps AI-origin detection independent of
catalog matching, prevents unresolved origin from being displayed alongside a contradictory product
pass, adds tested visible AI-label evidence, restores explainable non-probability scoring, and
provides a larger plain-language reviewer UI. It becomes `RUNTIME_READY` only after the named model
artifacts and real E2E cases pass on the target machine, and `DOMAIN_CALIBRATED` only after frozen,
disjoint calibration and locked-test evaluation.
