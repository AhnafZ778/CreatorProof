# CreatorProof v0.8.0 — packaging execution and audit report

Date: 2026-08-09  
Build signature: `CLEAR-ORIGIN-ENSEMBLE-2026.08.09`  
Promotion in this packaging workspace: **SOURCE_VERIFIED / TARGET-MACHINE MODEL ACTIVATION AND FULL
RUNTIME VALIDATION REQUIRED**

## 1. Outcome

v0.8 corrects the misleading “1% AI” failure rather than merely raising its displayed value. In
v0.7, Community Forensics received a non-upstream force-fit transform and the UI formatted a raw,
uncalibrated model response as a percentage. A single quiet detector could therefore look like a
confident human-origin result.

v0.8 now:

- uses the official Community Forensics 384px evaluation transform;
- stress-tests original, JPEG, resize, blur, center, and overlapping spatial views;
- groups detectors by evidence family before fusion;
- requires independent-family corroboration for a high AI-indicator result;
- requires multiple calibrated, independent families before any quiet result;
- abstains on limited coverage, low resolution, delivery instability, or family disagreement;
- uses the official GRIP `soft_or_prob` fused LLR through an isolated external adapter;
- removes uncalibrated origin percentages from the default UI;
- puts one bottom line, three plain-language lanes, and the next action before diagnostics;
- collapses scores, reason codes, ledgers, and forensic traces under **Technical evidence**;
- exposes build signature and active evidence families in health output;
- includes an end-to-end score collection and held-out calibration workflow.

This correction prevents unsupported negative certainty. It does not establish universal AI-image
detection.

## 2. Packaging environment

| Component | Observed version |
| --- | --- |
| Python | 3.12.13 |
| uv | 0.11.33 |
| Node.js | 24.14.0 |
| npm | 11.9.0 |
| Git | 2.51.1 |
| Git LFS | 3.4.1 |
| Next.js | 16.3.0 |
| CreatorProof API/Web | 0.8.0 |

## 3. Checks actually completed

### Backend static gates

Commands:

```bash
ruff format app tests scripts
ruff check app tests scripts
ruff format --check app tests scripts
```

Result:

- format: **PASS**, 68 files;
- lint: **PASS**;
- format verification: **PASS**.

The standalone locked Ruff executable from the adjacent source environment was used because the
copied packaging virtual environment deliberately contains no installed tools.

### Corrected origin behavior tests

The OpenCV import in this container terminates the process with exit 135, so the origin-only tests
were run with a minimal diagnostic OpenCV stub limited to the non-decision forensic trace function.
The learned origin policy, transforms, calibration registry, and adapter code remained unchanged.

Result: **13/13 PASS**.

Covered:

- one strong family can raise review but not claim corroborated origin;
- a single uncalibrated `0.01` response abstains and never implies human origin;
- transform instability abstains;
- trusted C2PA AI provenance takes precedence;
- no detector reports unavailable, not human;
- two stable independent strong families can support an AI-indicator result;
- two calibrated independent quiet families can support “no strong indicators,” not “human-made”;
- independent-family disagreement abstains;
- spatial uplift requires multi-crop support;
- official Community Forensics non-square preprocessing regression;
- calibration support/model-version gates;
- GRIP LLR boundary behavior;
- the adapter uses upstream `fusion`, not an invented average.

Non-failing warning: installed Starlette TestClient/httpx compatibility deprecation.

### Full backend suite

Command attempted:

```bash
python3 -m pytest -q
```

Result: **NOT VERIFIED IN THIS CONTAINER**. The process terminated with exit code 135 while importing
the host OpenCV binary. This is recorded as a packaging-environment blocker, not a passing test. The
unmodified full suite must be run on the target machine using `MASTER_EXECUTION_PROMPT_v0.8.md`.

### Frontend

Commands:

```bash
npm run typecheck
npm run build
```

Result:

- TypeScript: **PASS**;
- Next.js production build: **PASS**;
- all expected static and dynamic routes generated.

Non-failing warning: the host npm `http-proxy` config is deprecated for a future npm major.

### Browser observation

No live browser result is claimed from this packaging container. The real desktop/mobile,
keyboard, accessibility-tree, and five-second comprehension checks are mandatory on the target
machine.

## 4. Model and provider state in this archive

Model weights, third-party repositories, credentials, databases, and user images are intentionally
excluded.

| Provider | Packaged state | Required target-machine action |
| --- | --- | --- |
| SSCD copy retrieval | Source integration only | Fetch model and run `scripts.check_ai` |
| CSD learned style | Source integration only | Fetch runtime/checkpoint and require learned check |
| Community Forensics | Source integration only | Fetch official 384 safetensors and run origin check |
| GRIP CLIPDet | Clean adapter only | Clone official repo, Git-LFS weights, isolated environment, configure JSON adapter |
| C2PA | Boundary implemented | Install official `c2patool` |
| Local Merkle proof | Implemented/tested in v0.7 baseline | Verify receipts on target runtime |
| EAS anchor | Optional source boundary | Configure operator-provided testnet values only |
| OpenRouter | Optional/blank | Not required for detection |

No AI-origin accuracy metric is reported here because neither learned origin weights nor an
authorized generator-disjoint corpus is present.

## 5. Corrected origin decision contract

| Available evidence | User-facing result |
| --- | --- |
| Trusted signed AI-use assertion | Signed provenance identifies AI use |
| Two stable independent strong families | Multiple checks found AI-generation indicators |
| One responding family or incomplete calibration | Indicators need review / origin unknown |
| Strong family disagreement | Origin unknown; models disagreed |
| Unstable transforms or insufficient resolution | Origin unknown; evidence unreliable |
| Two independent, calibrated, quiet families | No strong indicators found; not proof of human origin |
| No active learned detector | AI-origin checks unavailable |

The default interface never renders `fused_detector_score` as a percent. A calibrated domain score is
shown only when every deciding family has accepted, model-version-matched held-out calibration and
minimum family coverage is met.

## 6. UI information hierarchy

The default case view is reduced to:

1. **Bottom line** — what requires attention;
2. **Origin / Copy / Style cards** — one plain conclusion each, clickable;
3. **Next action** — what the reviewer should do;
4. **Analysis modes** — detailed views only after selection;
5. **Technical evidence** — collapsed by default.

The origin view shows three facts before diagnostics: Content Credentials, model-family coverage, and
delivery robustness. Its dynamic conclusion is an atomic `role=status` region.

## 7. The supplied “1%” case

The v0.7 output cannot be converted into a valid 99%/1% conclusion after the fact. The previous value
was an uncalibrated raw response produced with the wrong preprocessing path and an incomplete model
configuration. v0.8 changes that outcome class to limited-coverage inconclusive when only one quiet,
uncalibrated family exists.

The supplied screenshot was not rescored in this packaging workspace because the original candidate
file, active model artifacts, and a calibrated runtime are absent. The target-machine prompt requires
the authorized original image to be run as a recorded E2E case. If the activated two-family system
still misses it, the case is a false negative and must remain in the locked validation/test evidence;
thresholds must not be lowered on that single example.

## 8. Remaining promotion blockers

1. Activate and hash-pin Community Forensics plus GRIP CLIPDet as two independent families.
2. Run all 28+ backend tests without the packaging container's OpenCV fault.
3. Build separate source/lineage- and generator-disjoint calibration, validation, and locked test
   sets for the ideathon art domain.
4. Run the real known-AI, human hard-negative, family-disagreement, transform-instability, retouched
   copy, and style-imitation E2E cases.
5. Complete live desktop/mobile/keyboard/accessibility UI observation.

## 9. Correct release statement

CreatorProof v0.8 is a source-verified correction that prevents a raw `0.01` detector output from
being presented as “1% AI,” restores the official Community Forensics input contract, adds
evidence-family and multi-crop origin fusion, integrates the official GRIP fusion through a clean
adapter, and replaces the cluttered evidence panel with a bottom-line-first interface. It becomes
`RUNTIME_READY` after the named artifacts are activated and all gates run on the target machine. It
becomes `DEMO_READY` only after real E2E and browser checks, and `DOMAIN_CALIBRATED` only after frozen,
disjoint calibration and locked-test evaluation.

